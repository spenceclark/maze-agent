"""Run configuration (spec §3, §8.1). Internal: never shown to agents."""

from math import ceil
from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from maze_lab.agent_contracts import AGENT_IDS, AgentId, Contract, NotebookOps, Objective

BaselinePolicyName = Literal["random_open_v1", "wall_follower_v1", "dfs_bounded_v1"]
LlmAdapter = Literal["pydantic_ai"]
LlmProvider = Literal[
    "anthropic", "openai", "ollama", "openrouter"
]  # "openai" = any OpenAI-compatible endpoint
LlmOutputMode = Literal["tool", "native", "prompted"]
Effort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
TimingMode = Literal["fixed_deadline", "barrier", "manual"]


# Landmark labels: neutral, unique object names with no order or position meaning (spec §4.4).
LANDMARK_LABELS: tuple[str, ...] = (
    "anchor", "anvil", "barrel", "basket", "bell", "bench", "cactus", "candle", "clock", "dice",
    "drum", "easel", "feather", "flag", "fountain", "globe", "guitar", "harp", "helmet", "kettle",
    "key", "ladder", "lamp", "lantern", "map", "mask", "mirror", "owl", "piano", "picture",
    "quilt", "rope", "shield", "statue", "teapot", "tree", "umbrella", "vase", "violin", "wheel",
)  # fmt: skip


class MazeSettings(Contract):
    width: int = Field(default=15, ge=2)
    height: int = Field(default=15, ge=2)
    generator: Literal["dfs_v1"] = "dfs_v1"
    extra_open_edges: int = Field(default=0, ge=0)
    exit_policy: Literal["uniform_perimeter_cell"] = "uniform_perimeter_cell"
    spawn_policy: Literal["uniform_distinct_non_exit"] = "uniform_distinct_non_exit"
    landmark_count: int = Field(default=0, ge=0)
    checkpoint_count: Literal[0] = 0  # checkpoints: phase 6

    @model_validator(mode="after")
    def _room_for_spawns(self) -> Self:
        if self.width * self.height < 4:
            raise ValueError("need at least four cells for three distinct non-exit spawns")
        if self.landmark_count > min(self.width * self.height, len(LANDMARK_LABELS)):
            raise ValueError(f"landmark_count must be at most {len(LANDMARK_LABELS)} and the number of cells")
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
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY"},
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
    # Prompt bytes per token assumed when sizing prompts against the context window. 1.0 is a hard
    # bound for byte-level tokenizers; 1.5 sits below the 1.67-1.91 measured on claude-haiku-5-5.
    context_bytes_per_token: float = Field(default=1.5, ge=1.0)
    sampling: Sampling = Sampling()
    max_output_tokens: int = Field(default=2048, ge=1)
    # Reasoning effort; None keeps the model's default. "none" turns reasoning off (OpenAI-compatible/Ollama).
    effort: Effort | None = None

    @model_validator(mode="after")
    def _effort_supported(self) -> Self:
        if self.effort is None:
            return self
        if self.provider == "openrouter":
            raise ValueError("effort is not wired for openrouter yet")
        if self.provider == "anthropic" and self.effort in ("none", "minimal"):
            raise ValueError("Anthropic effort must be low, medium, high, xhigh or max")
        return self

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
    # "splice" is spec §5.4; "append_rewrite" lets agents append or replace while the engine handles offsets.
    notebook_ops: NotebookOps = "splice"
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


def default_horizon(width: int, height: int) -> int:
    """The spec's reference horizon (500 ticks for 15x15) scaled by maze area."""
    return ceil(500 * width * height / (15 * 15))


class RunConfig(Contract):
    schema_version: Literal["1.0"] = "1.0"
    root_seed: int = Field(ge=0, lt=2**64)
    condition: str = Field(min_length=1)
    maze: MazeSettings = MazeSettings()
    agents: list[AgentConfig]
    rules: RulesConfig = RulesConfig()
    timing: TimingConfig = TimingConfig()
    horizon_ticks: int = Field(default=500, gt=0)  # when omitted, resolved from maze size
    prompt_version: str = "maze_agent_v4"
    max_provider_requests_per_turn: Literal[1] = 1
    snapshot_interval_ticks: int = Field(default=25, gt=0)

    @model_validator(mode="before")
    @classmethod
    def _horizon_from_maze_size(cls, data: Any) -> Any:
        """An omitted horizon scales with the maze, and the resolved value is stored."""
        if not isinstance(data, dict) or "horizon_ticks" in data:
            return data
        maze = data.get("maze", MazeSettings())
        if isinstance(maze, dict):
            maze = MazeSettings.model_validate(maze)
        if not isinstance(maze, MazeSettings):
            return data  # leave the error to field validation
        return {**data, "horizon_ticks": default_horizon(maze.width, maze.height)}

    @model_validator(mode="after")
    def _three_agents(self) -> Self:
        if tuple(a.id for a in self.agents) != AGENT_IDS:
            raise ValueError("agents must be exactly A, B, C in that order")
        return self
