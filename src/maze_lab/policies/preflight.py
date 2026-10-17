"""Context-capacity checks (spec §6.2).

Before a run starts, show that a worst-case turn fits each model: rules, an
observation with all three notebooks full, two full radio messages, the output
schema, and the reserved output. Incompatible configs are rejected; nothing is
ever dropped or truncated.

Prompt size is converted to tokens with the agent's `context_bytes_per_token`
(1.0 is a hard bound for byte-level tokenizers; the default 1.5 is below what
was measured on real prompts). The worst case fills notebooks with plain
text. Text that escapes to more bytes in JSON (control characters, quotes) is
caught per request by `check_prompt`, which refuses to send rather than let a
provider truncate silently, as Ollama does when its context is too small.
"""

import json
from math import ceil

from maze_lab.agent_contracts import (
    SPAWN_RECEIPT,
    AgentId,
    AgentRules,
    Budgets,
    LocalCell,
    Notebook,
    Observation,
    PeerRange,
    RadioObservation,
    TurnAction,
)
from maze_lab.config import LlmAgentConfig, RunConfig
from maze_lab.observation import public_rules
from maze_lab.policies.prompt import system_instruction, user_blocks

TEMPLATE_OVERHEAD_TOKENS = 1024  # chat template, tool wrapper, role markers
_SCHEMA_BYTES = len(json.dumps(TurnAction.model_json_schema()).encode())


def estimated_tokens(system: str, blocks: list[str], bytes_per_token: float) -> int:
    """Estimated input tokens for one request, including the output schema and template overhead."""
    size = len((system + "".join(blocks)).encode("utf-8")) + _SCHEMA_BYTES
    return ceil(size / bytes_per_token) + TEMPLATE_OVERHEAD_TOKENS


def check_prompt(agent: LlmAgentConfig, system: str, blocks: list[str]) -> str | None:
    """None if this request fits the agent's context window, else why not."""
    needed = estimated_tokens(system, blocks, agent.context_bytes_per_token) + agent.max_output_tokens
    if needed <= agent.context_window_tokens:
        return None
    window = agent.context_window_tokens
    return f"prompt needs ~{needed} tokens including reserved output; context_window_tokens is {window}"


def _worst_case_observation(rules: AgentRules, agent_id: AgentId, horizon: int) -> Observation:
    peers: list[AgentId] = [a for a in rules.agent_ids if a != agent_id]
    big = 10**9

    def full(owner: AgentId) -> Notebook:
        return Notebook.of(owner, big, "x" * rules.notebook_cap_bytes)

    return Observation(
        schema_version="1.0",
        agent_id=agent_id,
        decision_tick=horizon,
        state_tick=horizon - 1,
        has_reached_exit=False,
        local=LocalCell(
            north="interior_wall",
            east="interior_wall",
            south="interior_wall",
            west="interior_wall",
            is_exit=False,
            landmarks=[],
            checkpoints=[],
        ),
        exit_distance_tenths=big,
        peer_ranges=[PeerRange(agent_id=p, distance_tenths=big) for p in peers],
        last_action=SPAWN_RECEIPT.model_copy(update={"tick": horizon - 1}),
        notebook=full(agent_id),
        radio_inbox=[
            RadioObservation(sender=p, sent_tick=horizon - 1, text="x" * rules.radio_message_bytes)
            for p in peers
        ],
        colocated_notebooks=[full(p) for p in peers] if rules.meeting_notebooks_enabled else [],
        budgets=Budgets(
            notebook_cap_bytes=rules.notebook_cap_bytes,
            notebook_insert_bytes=rules.notebook_insert_bytes,
            radio_message_bytes=rules.radio_message_bytes,
            radio_next_eligible_tick=big,
            radio_enabled=rules.radio_enabled,
            notebook_enabled=rules.notebook_enabled,
            allow_stay=rules.allow_stay,
        ),
    )


def preflight(config: RunConfig) -> None:
    """Raise ValueError if any LLM agent's context cannot hold the worst-case turn."""
    rules = public_rules(config.rules, config.maze.landmark_count > 0)
    for agent in config.agents:
        if agent.kind != "llm":
            continue
        observation = _worst_case_observation(rules, agent.id, config.horizon_ticks)
        problem = check_prompt(
            agent, system_instruction(rules, agent.id, config.prompt_version), user_blocks(observation)
        )
        if problem is not None:
            raise ValueError(
                f"agent {agent.id} ({agent.model}): worst-case {problem}. Lower notebook_cap_bytes, "
                "disable meeting_notebooks_enabled, or reduce max_output_tokens."
            )
