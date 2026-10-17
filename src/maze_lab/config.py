"""Run configuration (spec §3, §8.1). Internal: never shown to agents."""

from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from maze_lab.agent_contracts import AGENT_IDS, AgentId, Contract, Objective

BaselinePolicyName = Literal["random_open_v1", "wall_follower_v1", "dfs_bounded_v1"]
LlmAdapter = Literal["pydantic_ai"]
LlmProvider = Literal["anthropic", "openai", "ollama"]  # "openai" = any OpenAI-compatible endpoint
LlmOutputMode = Literal["tool", "native", "prompted"]
TimingMode = Literal["fixed_deadline", "barrier", "manual"]


class MazeSettings(Contract):
    width: int = Field(default=15, ge=2)
    height: int = Field(default=15, ge=2)
    generator: Literal["dfs_v1"] = "dfs_v1"
    extra_open_edges: int = Field(default=0, ge=0)
    exit_policy: Literal["uniform_perimeter_cell"] = "uniform_perimeter_cell"
    spawn_policy: Literal["uniform_distinct_non_exit"] = "uniform_distinct_non_exit"
    landmark_count: Literal[0] = 0  # landmarks: phase 6
    checkpoint_count: Literal[0] = 0  # checkpoints: phase 6

    @model_validator(mode="after")
    def _room_for_spawns(self) -> Self:
        if self.width * self.height < 4:
            raise ValueError("need at least four cells for three distinct non-exit spawns")
        return self


class Sampling(Contract):
    temperature: float | None = None
    top_p: float | None = None
    seed: int | None = None


class BaselineAgentConfig(Contract):
    id: AgentId
    kind: Literal["baseline"]
    policy: BaselinePolicyName
    adapter: None = None
    provider: None = None
    model: None = None
    sampling: Sampling = Sampling()
    max_output_tokens: int = Field(default=2048, ge=1)


PROVIDER_DEFAULTS: dict[str, dict[str, str | None]] = {
    "anthropic": {"base_url": None, "api_key_env": "ANTHROPIC_API_KEY"},
    "openai": {"base_url": None, "api_key_env": "OPENAI_API_KEY"},
    "ollama": {"base_url": "http://localhost:11434/v1", "api_key_env": None},
}


class LlmAgentConfig(Contract):
    id: AgentId
    kind: Literal["llm"]
    policy: None = None
    adapter: LlmAdapter
    provider: LlmProvider
    model: str = Field(min_length=1)
    base_url: str | None
    api_key_env: str | None  # name of the server-side environment variable; never the key itself
    output_mode: LlmOutputMode = "tool"
    context_window_tokens: int = Field(gt=0)  # stated explicitly; checked by the prompt preflight
    sampling: Sampling = Sampling()
    max_output_tokens: int = Field(default=2048, ge=1)

    @model_validator(mode="before")
    @classmethod
    def _provider_defaults(cls, data: Any) -> Any:
        """Resolve provider defaults so the stored config is never ambiguous."""
        if isinstance(data, dict) and data.get("provider") in PROVIDER_DEFAULTS:
            return {**PROVIDER_DEFAULTS[data["provider"]], **data}
        return data


AgentConfig = Annotated[BaselineAgentConfig | LlmAgentConfig, Field(discriminator="kind")]


class RulesConfig(Contract):
    version: Literal["rules_v1"] = "rules_v1"
    objective: Objective = "all_reach_exit"
    allow_stay: bool = True
    notebook_enabled: bool = True
    notebook_cap_bytes: int = Field(default=8192, ge=0)
    notebook_insert_bytes: int = Field(default=1024, ge=0)
    radio_enabled: bool = True
    radio_message_bytes: int = Field(default=280, ge=0)
    radio_cooldown_ticks: int = Field(default=5, ge=0)
    meeting_notebooks_enabled: bool = True
    distance_sensors: Literal["exit_and_peers"] = "exit_and_peers"  # variants: phase 6
    distance_quantization: Literal["tenths"] = "tenths"

    @model_validator(mode="after")
    def _absence_semantics(self) -> Self:
        if not self.notebook_enabled and (self.notebook_cap_bytes or self.notebook_insert_bytes):
            raise ValueError("a disabled notebook must have zero cap and insert budget")
        if not self.radio_enabled and self.radio_message_bytes:
            raise ValueError("disabled radio must have a zero message budget")
        return self


class TimingConfig(Contract):
    mode: TimingMode = "fixed_deadline"
    decision_window_ms: int = Field(default=30_000, gt=0)


class RunConfig(Contract):
    schema_version: Literal["1.0"] = "1.0"
    root_seed: int = Field(ge=0, lt=2**64)
    condition: str = Field(min_length=1)
    maze: MazeSettings = MazeSettings()
    agents: list[AgentConfig]
    rules: RulesConfig = RulesConfig()
    timing: TimingConfig = TimingConfig()
    horizon_ticks: int = Field(default=500, gt=0)
    prompt_version: str = "maze_agent_v1"
    max_provider_requests_per_turn: Literal[1] = 1
    snapshot_interval_ticks: int = Field(default=25, gt=0)

    @model_validator(mode="after")
    def _three_agents(self) -> Self:
        if tuple(a.id for a in self.agents) != AGENT_IDS:
            raise ValueError("agents must be exactly A, B, C in that order")
        return self
