"""Gameplay facts emitted by the reducer (spec §10).

The coordinator wraps these in sequenced `EventEnvelope`s and adds the
run-level events (`run.*`, `tick.committed`).
"""

from typing import Annotated, Literal

from pydantic import Field

from maze_lab.agent_contracts import ActionReceipt, AgentId, AnyTurnAction, Contract, NotebookEdit
from maze_lab.domain.geometry import Position


class DecisionResolved(Contract):
    type: Literal["agent.decision_resolved"] = "agent.decision_resolved"
    agent_id: AgentId
    action: AnyTurnAction | None  # None when the decision itself failed
    receipt: ActionReceipt
    invocation_id: str | None


class NotebookUpdated(Contract):
    type: Literal["notebook.updated"] = "notebook.updated"
    agent_id: AgentId
    previous_revision: int
    new_revision: int
    splice: NotebookEdit
    dropped_codepoints: int = Field(default=0, ge=0)  # append_log: oldest text dropped after the splice
    text: str
    sha256: str


class RadioSent(Contract):
    type: Literal["radio.sent"] = "radio.sent"
    sender: AgentId
    sent_tick: int
    visible_decision_tick: int
    recipients: list[AgentId]
    text: str
    utf8_bytes: int


class MeetingObserved(Contract):
    type: Literal["meeting.observed"] = "meeting.observed"
    agents: list[AgentId]
    position: Position


class ExitReached(Contract):
    type: Literal["agent.exit_reached"] = "agent.exit_reached"
    agent_id: AgentId
    tick: int


GameEvent = Annotated[
    DecisionResolved | NotebookUpdated | RadioSent | MeetingObserved | ExitReached,
    Field(discriminator="type"),
]
