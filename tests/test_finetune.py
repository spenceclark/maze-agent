"""Fine-tuning dataset: the expert's memory lives in its notebook, and the prompts match the live adapter."""

import asyncio
import json
from pathlib import Path

import httpx2 as httpx  # the openai SDK client is built on httpx2
import pytest
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from maze_lab.agent_contracts import Notebook, Observation
from maze_lab.config import RunConfig
from maze_lab.finetune.dataset import (
    DatasetError,
    Row,
    check_target,
    expert,
    game_config,
    play,
    read_rows,
    verify,
    write_games,
)
from maze_lab.finetune.expert import MissingMemory, decide, reply_json
from maze_lab.observation import public_rules
from maze_lab.policies.pydantic_ai_adapter import PydanticAiPolicy

TARGET = RunConfig.model_validate_json(
    (Path(__file__).parents[1] / "configs" / "qwen35_9b_v10_helping_hands_nothink.json").read_text()
)


@pytest.fixture(scope="module")
def game() -> list[Row]:
    return play(game_config(TARGET, seed=3, size=10), expert)


def observation_from_prompt(row: Row) -> Observation:
    """Rebuild what the expert may use from the prompt text alone: the observation JSON plus the
    notebook text between its markers (revision and byte counts are not shown, and not needed)."""
    agent = row["meta"]["agent"]
    notebook_block, _peers, observation_block = (m["content"] for m in row["messages"][1:4])
    text = notebook_block.split(f"<<<NOTEBOOK {agent}\n", 1)[1].rsplit(f"\nNOTEBOOK {agent}>>>", 1)[0]
    data = json.loads(observation_block.split("\n", 1)[1])
    data["notebook"] = Notebook.of(agent, 0, text).model_dump()
    data["colocated_notebooks"] = []
    return Observation.model_validate_json(json.dumps(data))


def test_every_size_is_won_without_walking_into_a_wall():
    for seed, size in [(11, 8), (12, 12), (13, 15)]:
        rows = play(game_config(TARGET, seed, size), expert)  # raises on a wall, a dropped line, or a loss
        assert {r["meta"]["agent"] for r in rows} == {"A", "B", "C"}


def test_each_decision_is_derivable_from_the_prompt_alone(game: list[Row]):
    for row in game:
        obs = observation_from_prompt(row)
        assert reply_json(obs, decide(obs)) == row["messages"][-1]["content"]


def test_backtracking_through_a_junction_comes_from_the_notebook(game: list[Row]):
    rows = [r for r in game if "notebook says junction" in r["messages"][-1]["content"]]
    assert rows, "this game should backtrack through at least one junction"
    for row in rows:
        obs = observation_from_prompt(row)
        forgotten = obs.notebook.text.replace("junction", "forgotten")
        stripped = obs.model_copy(update={"notebook": Notebook.of(obs.agent_id, 0, forgotten)})
        with pytest.raises(MissingMemory):
            decide(stripped)


def test_junction_lines_are_written_once_and_never_for_the_start(game: list[Row]):
    notes = [json.loads(r["messages"][-1]["content"])["notebook_append"] for r in game]
    lines = [line for note in notes if note for line in note.split("; ") if line.startswith("junction")]
    for agent in "ABC":
        mine = [
            line
            for r, note in zip(game, notes, strict=True)
            if note and r["meta"]["agent"] == agent
            for line in note.split("; ")
            if line.startswith("junction")
        ]
        assert len(mine) == len(set(mine))
    assert lines and not any(line.startswith("junction [0,0]") for line in lines)


def test_replay_accepts_the_written_file_and_rejects_a_tampered_one(tmp_path: Path):
    out = tmp_path / "train.jsonl"
    stats = write_games(TARGET, [(21, 8), (22, 10)], out)
    assert (stats.won, stats.games) == (2, 2)
    assert verify(TARGET, read_rows(out)) == 2

    rows = list(read_rows(out))
    reply = json.loads(rows[0]["messages"][-1]["content"])
    wall = next(
        d for d, e in zip("NESW", reply["check"].split("; ")[1].split(", "), strict=True) if "open" not in e
    )
    reply["move"] = wall
    rows[0]["messages"][-1]["content"] = json.dumps(reply)
    with pytest.raises(DatasetError, match="blocked"):
        verify(TARGET, rows)


def test_targets_without_the_expected_variants_are_refused():
    rules = TARGET.rules.model_copy(update={"used_exits_enabled": False})
    with pytest.raises(DatasetError, match="used_exits"):
        check_target(TARGET.model_copy(update={"rules": rules}))


def _ollama_split(messages: list[dict[str, object]]) -> list[dict[str, str]]:
    """Ollama's OpenAI endpoint turns each text part of a message into its own message, same role."""
    out: list[dict[str, str]] = []
    for m in messages:
        content = m["content"]
        parts = [p["text"] for p in content] if isinstance(content, list) else [content]  # pyright: ignore[reportUnknownVariableType]
        out += [{"role": str(m["role"]), "content": str(p)} for p in parts]  # pyright: ignore[reportUnknownVariableType]
    return out


def test_prompts_match_what_the_live_adapter_sends():
    """Play a game where every decision also goes through the live adapter, against a fake Ollama
    server answering with the expert's reply; the wire request must be the dataset's prompt."""
    sent: list[dict[str, object]] = []
    reply = {"text": ""}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        message = {"role": "assistant", "content": reply["text"]}
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "qwen3.5:9b",
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncOpenAI(base_url="http://ollama.test/v1", api_key="unused", http_client=http)
    model = OpenAIChatModel("qwen3.5:9b", provider=OpenAIProvider(openai_client=client))
    config = check_target(TARGET)
    agent_rules = public_rules(TARGET.rules, TARGET.maze.landmark_count > 0)

    def through_adapter(obs: Observation, messages: list[dict[str, str]]) -> str:
        reply["text"] = expert(obs, messages)
        agent = config.model_copy(update={"id": obs.agent_id})
        live = PydanticAiPolicy(agent, timeout_s=5, prompt_version=TARGET.prompt_version, model=model)
        attempt = asyncio.run(live.decide(obs, agent_rules))
        assert attempt.action is not None, attempt.error_detail
        assert _ollama_split(sent[-1]["messages"]) == messages  # pyright: ignore[reportArgumentType]
        assert attempt.response_text == reply["text"]
        return reply["text"]

    rows = play(game_config(TARGET, seed=4, size=8), through_adapter)
    assert len(sent) == len(rows)
    assert any(json.loads(r["messages"][-1]["content"])["notebook_append"] for r in rows)
