"""Committed world state (spec §8). Ground truth: spectator/scorer only."""

from typing import Self

from pydantic import Field, model_validator

from maze_lab.agent_contracts import (
    AGENT_IDS,
    SPAWN_RECEIPT,
    ActionReceipt,
    AgentId,
    Contract,
    Notebook,
    RadioObservation,
)
from maze_lab.domain.geometry import Position
from maze_lab.domain.maze import MazeDefinition

TRAIL_TICKS = 30  # ponytail: fixed trail length; make it a rules knob if runs need to tune it


class AgentState(Contract):
    agent_id: AgentId
    position: Position
    notebook: Notebook
    last_receipt: ActionReceipt
    last_radio_tick: int | None
    first_exit_tick: int | None
    successful_moves: int = Field(ge=0)
    # Kept only with rules.coordinates_enabled; left out of the JSON when empty, so states stored
    # before trails existed keep their hashes.
    trail: list[Position] = Field(default_factory=list, exclude_if=lambda v: not v)


class WorldState(Contract):
    tick: int = Field(ge=0)
    agents: list[AgentState]  # A, B, C
    radio_batch: list[RadioObservation]  # sent at `tick`, heard only at tick + 1
    meetings: list[list[AgentId]]
    objective_met_tick: int | None

    def agent(self, agent_id: AgentId) -> AgentState:
        return self.agents[AGENT_IDS.index(agent_id)]

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if tuple(a.agent_id for a in self.agents) != AGENT_IDS:
            raise ValueError("agents must be A, B, C in order")
        return self


def meeting_groups(agents: list[AgentState]) -> list[list[AgentId]]:
    """Groups of two or more agents sharing an end-of-tick cell, sorted."""
    by_cell: dict[Position, list[AgentId]] = {}
    for a in agents:
        by_cell.setdefault(a.position, []).append(a.agent_id)
    return sorted(ids for ids in by_cell.values() if len(ids) >= 2)


def initial_state(maze: MazeDefinition) -> WorldState:
    agents = [
        AgentState(
            agent_id=agent_id,
            position=spawn,
            notebook=Notebook.of(agent_id, 0, ""),
            last_receipt=SPAWN_RECEIPT,
            last_radio_tick=None,
            first_exit_tick=None,
            successful_moves=0,
        )
        for agent_id, spawn in zip(AGENT_IDS, maze.spawns, strict=True)
    ]
    return WorldState(
        tick=0, agents=agents, radio_batch=[], meetings=meeting_groups(agents), objective_met_tick=None
    )
