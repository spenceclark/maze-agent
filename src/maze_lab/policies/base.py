"""The policy boundary (spec §6.1).

A policy sees one `Observation` plus public `AgentRules` and returns a
`DecisionAttempt`. It gets no world state, seed, storage, or history; any
memory must live in the agent's own notebook.
"""

from typing import Protocol, Self

from pydantic import Field, model_validator

from maze_lab.agent_contracts import AgentRules, AnyTurnAction, Contract, ForcedStayCause, Observation


class Usage(Contract):
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    cache_read_tokens: int | None = None  # included in input_tokens
    cache_write_tokens: int | None = None  # included in input_tokens
    requests: int = Field(default=0, ge=0)
    estimated_cost_usd: float | None = None  # provider price table at call time, when known


class DecisionAttempt(Contract):
    """A policy's answer: an action, or the reason it has none, plus provider metadata."""

    action: AnyTurnAction | None
    failure: ForcedStayCause | None
    request_text: str | None = None  # exact prompt sent (LLM policies)
    response_text: str | None = None  # exact text returned (LLM policies)
    provider_request_id: str | None = None
    usage: Usage = Usage()
    error_detail: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.action is None) == (self.failure is None):
            raise ValueError("provide exactly one of action or failure")
        return self


class AgentPolicy(Protocol):
    async def decide(self, observation: Observation, rules: AgentRules) -> DecisionAttempt: ...
