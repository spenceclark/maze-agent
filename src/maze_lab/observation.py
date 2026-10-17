"""The sole projection from ground truth to what an agent sees (spec §4.2).

Nothing else may build an `Observation` or `AgentRules`. Coordinates, maze
size, seeds, and spectator data stop here.
"""

from maze_lab.agent_contracts import (
    AGENT_IDS,
    AgentId,
    AgentRules,
    Budgets,
    LocalCell,
    Observation,
    PeerRange,
)
from maze_lab.config import RulesConfig
from maze_lab.domain.geometry import distance_tenths
from maze_lab.domain.maze import MazeDefinition
from maze_lab.domain.radio import next_eligible_tick
from maze_lab.domain.state import WorldState


def public_rules(rules: RulesConfig) -> AgentRules:
    return AgentRules(
        version=rules.version,
        agent_ids=list(AGENT_IDS),
        objective=rules.objective,
        allow_stay=rules.allow_stay,
        notebook_enabled=rules.notebook_enabled,
        notebook_cap_bytes=rules.notebook_cap_bytes,
        notebook_insert_bytes=rules.notebook_insert_bytes,
        radio_enabled=rules.radio_enabled,
        radio_message_bytes=rules.radio_message_bytes,
        radio_cooldown_ticks=rules.radio_cooldown_ticks,
        meeting_notebooks_enabled=rules.meeting_notebooks_enabled,
        checkpoint_labels=[],
        max_provider_requests_per_turn=1,
    )


def observe(maze: MazeDefinition, rules: RulesConfig, state: WorldState, agent_id: AgentId) -> Observation:
    me = state.agent(agent_id)
    cell = maze.cell(me.position)
    group = next((g for g in state.meetings if agent_id in g), [])
    colocated = (
        [state.agent(peer).notebook for peer in group if peer != agent_id]
        if rules.meeting_notebooks_enabled
        else []
    )
    return Observation(
        schema_version="1.0",
        agent_id=agent_id,
        decision_tick=state.tick + 1,
        state_tick=state.tick,
        has_reached_exit=me.first_exit_tick is not None,
        local=LocalCell(
            north=cell.north,
            east=cell.east,
            south=cell.south,
            west=cell.west,
            is_exit=me.position == maze.exit,
            landmarks=[],
            checkpoints=[],
        ),
        exit_distance_tenths=distance_tenths(me.position, maze.exit),
        peer_ranges=[
            PeerRange(agent_id=p.agent_id, distance_tenths=distance_tenths(me.position, p.position))
            for p in state.agents
            if p.agent_id != agent_id
        ],
        last_action=me.last_receipt,
        notebook=me.notebook,
        radio_inbox=[m for m in state.radio_batch if m.sender != agent_id],
        colocated_notebooks=colocated,
        budgets=Budgets(
            notebook_cap_bytes=rules.notebook_cap_bytes,
            notebook_insert_bytes=rules.notebook_insert_bytes,
            radio_message_bytes=rules.radio_message_bytes,
            radio_next_eligible_tick=max(
                state.tick + 1, next_eligible_tick(me.last_radio_tick, rules.radio_cooldown_ticks)
            ),
            radio_enabled=rules.radio_enabled,
            notebook_enabled=rules.notebook_enabled,
            allow_stay=rules.allow_stay,
        ),
    )
