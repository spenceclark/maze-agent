"""PydanticAI adapter contract tests with a scripted model; no provider calls (spec §17).

Audits: one request per decision, no carried history, no output repair, and
the strict parser applied to whatever the model returned.
"""

import asyncio
import json
from collections.abc import Callable

import pytest
from helpers import RULES, P, grid
from pydantic import ValidationError
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from maze_lab.agent_contracts import Observation
from maze_lab.config import LlmAgentConfig, RunConfig
from maze_lab.domain.state import initial_state
from maze_lab.observation import observe, public_rules
from maze_lab.policies.base import DecisionAttempt
from maze_lab.policies.preflight import preflight
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
        prompt = "".join(str(getattr(p, "content", "")) for p in messages[0].parts)
        assert OBS.model_dump_json() in prompt


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
    assert sent["user"].endswith(OBS.model_dump_json())
    assert "agent A" in sent["system"] and sent["output_mode"] == "tool"


def test_provider_defaults_are_resolved_explicitly():
    assert llm_config().api_key_env == "ANTHROPIC_API_KEY"
    ollama = llm_config(provider="ollama", model="qwen3:14b")
    assert ollama.base_url == "http://localhost:11434/v1" and ollama.api_key_env is None
    with pytest.raises(ValidationError):
        LlmAgentConfig.model_validate({"id": "A", "kind": "llm", "adapter": "pydantic_ai", "provider": "x"})


def _run_config(context: int) -> RunConfig:
    agent = llm_config(context_window_tokens=context).model_dump()
    return RunConfig.model_validate(
        {"root_seed": 1, "condition": "pilot", "agents": [agent | {"id": a} for a in "ABC"]}
    )


def test_preflight_accepts_large_context_and_rejects_small():
    preflight(_run_config(200_000))
    with pytest.raises(ValueError, match="worst-case turn"):
        preflight(_run_config(32_000))
