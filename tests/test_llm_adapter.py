"""PydanticAI adapter contract tests with a scripted model; no provider calls (spec §17).

Audits: one request per decision, no carried history, no output repair, and
the strict parser applied to whatever the model returned.
"""

import asyncio
import json
from collections.abc import Callable

import pytest
from helpers import RULES, P, act, grid, step
from pydantic import ValidationError
from pydantic_ai.messages import (
    CachePoint,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from maze_lab.agent_contracts import Observation
from maze_lab.config import LlmAgentConfig, RunConfig
from maze_lab.domain.state import initial_state
from maze_lab.observation import observe, public_rules
from maze_lab.policies.base import DecisionAttempt
from maze_lab.policies.preflight import preflight
from maze_lab.policies.prompt import system_instruction, user_blocks
from maze_lab.policies.pydantic_ai_adapter import PydanticAiPolicy

MAZE = grid(3, 3, P(2, 2), [P(0, 0), P(1, 0), P(0, 1)])
OBS = observe(MAZE, RULES, initial_state(MAZE), "A")
AGENT_RULES = public_rules(RULES)

Responder = Callable[[list[ModelMessage], AgentInfo], ModelResponse]


def llm_config(output_mode: str = "tool", **extra: object) -> LlmAgentConfig:
    return LlmAgentConfig.model_validate(
        {
            "id": "A",
            "kind": "llm",
            "adapter": "pydantic_ai",
            "provider": "anthropic",
            "model": "claude-haiku-5-5",
            "output_mode": output_mode,
            "context_window_tokens": 200_000,
            **extra,
        }
    )


def valid_args(tick: int = 1) -> dict[str, object]:
    return {"schema_version": "1.0", "tick": tick, "move": "S", "notebook_edit": None, "radio": "hi"}


class Recorder:
    """Scripted model that records every request it receives."""

    def __init__(self, respond: Responder) -> None:
        self.calls: list[list[ModelMessage]] = []
        self._respond = respond

    def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.calls.append(messages)
        return self._respond(messages, info)


def decide(
    respond: Responder, output_mode: str = "tool", obs: Observation = OBS
) -> tuple[DecisionAttempt, Recorder]:
    recorder = Recorder(respond)
    policy = PydanticAiPolicy(llm_config(output_mode), timeout_s=5, model=FunctionModel(recorder))
    return asyncio.run(policy.decide(obs, AGENT_RULES)), recorder


def tool_call(args: str | dict[str, object]) -> Responder:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=args)])

    return respond


def text(content: str) -> Responder:
    return lambda messages, info: ModelResponse(parts=[TextPart(content=content)])


def test_valid_tool_call_is_one_request():
    attempt, recorder = decide(tool_call(valid_args()))
    assert attempt.failure is None and attempt.action is not None
    assert attempt.action.move == "S" and attempt.action.radio == "hi"
    assert len(recorder.calls) == 1 and attempt.usage.requests == 1
    assert attempt.response_text is not None and json.loads(attempt.response_text) == valid_args()


def test_fresh_invocation_carries_no_history():
    recorder = Recorder(tool_call(valid_args()))
    policy = PydanticAiPolicy(llm_config(), timeout_s=5, model=FunctionModel(recorder))
    asyncio.run(policy.decide(OBS, AGENT_RULES))
    asyncio.run(policy.decide(OBS, AGENT_RULES))
    for messages in recorder.calls:
        assert len(messages) == 1 and isinstance(messages[0], ModelRequest)
        user = next(p for p in messages[0].parts if isinstance(p, UserPromptPart))
        assert [c for c in user.content if isinstance(c, str)] == user_blocks(OBS)
        assert any(isinstance(c, CachePoint) for c in user.content)


def test_prompt_blocks_hold_the_whole_observation_stable_parts_first():
    state = step(MAZE, initial_state(MAZE), A=act(1, "E", edit=(0, 0, 0, "note"))).state
    obs = observe(MAZE, RULES, state, "B")
    own, peers, rest = (json.loads(b.split("\n", 1)[1]) for b in user_blocks(obs))
    rebuilt = Observation.model_validate({**rest, "notebook": own, "colocated_notebooks": peers})
    assert rebuilt == obs and peers  # B shares a cell with A after tick 1
    assert "decision_tick" in rest and "decision_tick" not in json.dumps(own)


def test_cache_tokens_are_recorded():
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        usage = RequestUsage(
            input_tokens=1000, output_tokens=50, cache_read_tokens=700, cache_write_tokens=200
        )
        return ModelResponse(
            parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=valid_args())], usage=usage
        )

    attempt, _ = decide(respond)
    assert (
        attempt.usage.input_tokens,
        attempt.usage.cache_read_tokens,
        attempt.usage.cache_write_tokens,
    ) == (
        1000,
        700,
        200,
    )


def test_prompt_too_big_for_context_is_never_sent():
    recorder = Recorder(tool_call(valid_args()))
    small = llm_config(context_window_tokens=3000)
    attempt = asyncio.run(
        PydanticAiPolicy(small, timeout_s=5, model=FunctionModel(recorder)).decide(OBS, AGENT_RULES)
    )
    assert attempt.failure == "provider_error" and "context_window_tokens" in (attempt.error_detail or "")
    assert recorder.calls == [] and attempt.usage.requests == 0


def test_schema_failure_is_not_repaired():
    attempt, recorder = decide(tool_call({"move": "S"}))
    assert attempt.failure == "invalid_action" and attempt.action is None
    assert len(recorder.calls) == 1


def test_text_instead_of_tool_call_is_not_repaired():
    attempt, recorder = decide(text("I will go south."))
    assert attempt.failure == "invalid_action"
    assert len(recorder.calls) == 1


def test_duplicate_keys_rejected_by_strict_parser():
    raw = '{"schema_version":"1.0","tick":1,"move":"S","move":"N","notebook_edit":null,"radio":null}'
    attempt, recorder = decide(tool_call(raw))
    assert attempt.failure == "invalid_action" and attempt.response_text == raw
    assert len(recorder.calls) == 1


def test_prompted_mode_rejects_trailing_prose():
    attempt, _ = decide(text(json.dumps(valid_args()) + " hope that helps"), output_mode="prompted")
    assert attempt.failure == "invalid_action"
    good, _ = decide(text(json.dumps(valid_args())), output_mode="prompted")
    assert good.action is not None and good.action.move == "S"


def test_wrong_tick_passes_adapter_and_is_left_to_the_reducer():
    attempt, _ = decide(tool_call(valid_args(tick=9)))
    assert attempt.action is not None and attempt.action.tick == 9


def test_request_text_records_exact_inputs():
    attempt, _ = decide(tool_call(valid_args()))
    sent = json.loads(attempt.request_text or "")
    assert sent["user_blocks"] == user_blocks(OBS)
    assert "agent A" in sent["system"] and sent["output_mode"] == "tool"


def test_provider_defaults_are_resolved_explicitly():
    assert llm_config().api_key_env == "ANTHROPIC_API_KEY"
    ollama = llm_config(provider="ollama", model="qwen3:14b")
    assert ollama.base_url == "http://localhost:11434/v1" and ollama.api_key_env is None
    with pytest.raises(ValidationError):
        LlmAgentConfig.model_validate({"id": "A", "kind": "llm", "adapter": "pydantic_ai", "provider": "x"})


def _run_config(context: int, output: int = 2048, **rules: object) -> RunConfig:
    agent = llm_config(context_window_tokens=context, max_output_tokens=output).model_dump()
    return RunConfig.model_validate(
        {"root_seed": 1, "condition": "pilot", "agents": [agent | {"id": a} for a in "ABC"], "rules": rules}
    )


def test_preflight_sizes_local_contexts_realistically():
    preflight(_run_config(32_000))  # default caps fit a 32k model
    with pytest.raises(ValueError, match="worst-case"):
        preflight(_run_config(8_192))  # three full 8 KiB notebooks do not fit 8k
    # An 8k model fits once notebooks are smaller and peer notebooks are off.
    preflight(_run_config(8_192, output=1024, notebook_cap_bytes=2048, meeting_notebooks_enabled=False))


def test_rules_warn_that_straight_line_distance_ignores_walls():
    text = system_instruction(AGENT_RULES, "A")
    assert "ignoring walls" in text and "dead end" in text


def test_truncated_output_is_reported_as_truncation():
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        cut = '{"schema_version":"1.0","tick":1,"move":"S","notebook_edit":null,"radio":"cut off'
        return ModelResponse(parts=[TextPart(content=cut)], finish_reason="length")

    attempt, recorder = decide(respond, output_mode="native")
    assert attempt.failure == "invalid_action" and attempt.error_detail == "output truncated at max_tokens"
    assert len(recorder.calls) == 1
