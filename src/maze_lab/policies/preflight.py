"""Context-capacity preflight (spec §6.2).

Before a run starts, prove the worst-case prompt fits each model: rules, an
observation with all three notebooks full, two full radio messages, the output
schema, and the reserved output. Incompatible configs are rejected; nothing is
ever dropped or truncated at run time.

Bound: one token encodes at least one UTF-8 byte for byte-level BPE
tokenizers, so prompt bytes bound prompt tokens. Notebooks are filled with
NUL characters, the content with the largest JSON escape (6 bytes per byte).
"""

import json

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
from maze_lab.config import RunConfig
from maze_lab.observation import public_rules
from maze_lab.policies.prompt import system_instruction, user_message

TEMPLATE_OVERHEAD_TOKENS = 1024  # chat template, tool wrapper, role markers


def _worst_case_observation(rules: AgentRules, agent_id: AgentId, horizon: int) -> Observation:
    peers: list[AgentId] = [a for a in rules.agent_ids if a != agent_id]
    big = 10**9

    def full(owner: AgentId) -> Notebook:
        return Notebook.of(owner, big, "\x00" * rules.notebook_cap_bytes)

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
            RadioObservation(sender=p, sent_tick=horizon - 1, text="\x00" * rules.radio_message_bytes)
            for p in peers
        ],
        colocated_notebooks=[full(p) for p in peers],
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


def worst_case_input_tokens(rules: AgentRules, agent_id: AgentId, horizon: int) -> int:
    observation = _worst_case_observation(rules, agent_id, horizon)
    text = (
        system_instruction(rules, agent_id)
        + user_message(observation)
        + json.dumps(TurnAction.model_json_schema())
    )
    return len(text.encode("utf-8")) + TEMPLATE_OVERHEAD_TOKENS


def preflight(config: RunConfig) -> None:
    """Raise ValueError if any LLM agent's context cannot hold the worst-case turn."""
    rules = public_rules(config.rules)
    for agent in config.agents:
        if agent.kind != "llm":
            continue
        needed = worst_case_input_tokens(rules, agent.id, config.horizon_ticks) + agent.max_output_tokens
        if needed > agent.context_window_tokens:
            raise ValueError(
                f"agent {agent.id} ({agent.model}): worst-case turn needs {needed} tokens "
                f"but context_window_tokens is {agent.context_window_tokens}"
            )
