"""The pure simultaneous tick reducer (spec §5, §9).

`resolve(S_(t-1), actions) -> (S_t, events)`. Every component is judged
against the frozen previous state, so the outcome is independent of the order
in which decisions arrived. No I/O, clocks, or randomness.
"""

from collections.abc import Mapping
from typing import NamedTuple, Self

from pydantic import model_validator

from maze_lab.agent_contracts import (
    ACCEPTED,
    AGENT_IDS,
    NOT_REQUESTED,
    OPPOSITE,
    ActionReceipt,
    AgentId,
    AnyTurnAction,
    ComponentReceipt,
    Contract,
    ForcedStayCause,
    MovementReceipt,
    RadioObservation,
    utf8_len,
)
from maze_lab.config import RulesConfig
from maze_lab.domain.events import (
    DecisionResolved,
    ExitReached,
    GameEvent,
    MeetingObserved,
    NotebookUpdated,
    RadioSent,
)
from maze_lab.domain.maze import MazeDefinition
from maze_lab.domain.notebook import apply_change, requested_change
from maze_lab.domain.radio import check_radio
from maze_lab.domain.state import TRAIL_TICKS, AgentState, WorldState, meeting_groups
from maze_lab.hashing import sha256_hex


class Submission(Contract):
    """What the coordinator collected for one agent: an action, or why there is none."""

    action: AnyTurnAction | None
    failure: ForcedStayCause | None
    invocation_id: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.action is None) == (self.failure is None):
            raise ValueError("provide exactly one of action or failure")
        return self


class TickResult(NamedTuple):
    state: WorldState
    events: list[GameEvent]


def _rejected(code: str) -> ComponentReceipt:
    return ComponentReceipt(status="rejected", code=code)


def _resolve_agent(
    maze: MazeDefinition, rules: RulesConfig, prev: AgentState, sub: Submission, tick: int
) -> tuple[AgentState, list[GameEvent], RadioObservation | None]:
    action, failure = sub.action, sub.failure
    if action is not None and action.tick != tick:
        failure = "stale_tick"

    position, arrived_from, moves = prev.position, None, prev.successful_moves
    notebook, last_radio = prev.notebook, prev.last_radio_tick
    nb_receipt, radio_receipt = NOT_REQUESTED, NOT_REQUESTED
    events: list[GameEvent] = []
    radio: RadioObservation | None = None

    if failure is not None:
        # Whole action rejected: no partial effects.
        attempted, outcome, cause = (action.move if action else None), "forced_stay", failure
        if action is not None and requested_change(action):
            nb_receipt = _rejected("action_rejected")
        if action is not None and action.radio is not None:
            radio_receipt = _rejected("action_rejected")
    else:
        assert action is not None
        attempted, cause = action.move, None
        if action.move == "STAY":
            outcome = "stayed" if rules.allow_stay else "forced_stay"
            cause = None if rules.allow_stay else "stay_disabled"
        elif maze.edge(prev.position, action.move) == "open":
            outcome, position, arrived_from = "moved", prev.position.step(action.move), OPPOSITE[action.move]
            moves += 1
        else:
            outcome, cause = "blocked", "wall"

        if requested_change(action):
            result = (
                apply_change(action, notebook, rules.notebook_cap_bytes, rules.notebook_insert_bytes)
                if rules.notebook_enabled
                else "feature_disabled"
            )
            if isinstance(result, str):
                nb_receipt = _rejected(result)
            else:
                updated, edit, dropped = result
                events.append(
                    NotebookUpdated(
                        agent_id=prev.agent_id,
                        previous_revision=notebook.revision,
                        new_revision=updated.revision,
                        splice=edit,
                        dropped_codepoints=dropped,
                        text=updated.text,
                        sha256=sha256_hex(updated.text),
                    )
                )
                notebook, nb_receipt = updated, ACCEPTED

        if (text := action.radio) is not None:
            code = (
                check_radio(text, tick, last_radio, rules.radio_cooldown_ticks, rules.radio_message_bytes)
                if rules.radio_enabled
                else "feature_disabled"
            )
            if code is not None:
                radio_receipt = _rejected(code)
            else:
                radio, last_radio, radio_receipt = (
                    RadioObservation(sender=prev.agent_id, sent_tick=tick, text=text),
                    tick,
                    ACCEPTED,
                )

    receipt = ActionReceipt(
        tick=tick,
        movement=MovementReceipt(
            attempted=attempted, outcome=outcome, arrived_from=arrived_from, cause=cause
        ),
        notebook=nb_receipt,
        radio=radio_receipt,
    )
    events.insert(
        0,
        DecisionResolved(
            agent_id=prev.agent_id, action=action, receipt=receipt, invocation_id=sub.invocation_id
        ),
    )
    first_exit = prev.first_exit_tick
    if first_exit is None and position == maze.exit:
        first_exit = tick
    new_state = AgentState(
        agent_id=prev.agent_id,
        position=position,
        notebook=notebook,
        last_receipt=receipt,
        last_radio_tick=last_radio,
        first_exit_tick=first_exit,
        successful_moves=moves,
        trail=[*prev.trail, prev.position][-TRAIL_TICKS:] if rules.coordinates_enabled else [],
    )
    return new_state, events, radio


def _objective_met(maze: MazeDefinition, rules: RulesConfig, agents: list[AgentState]) -> bool:
    match rules.objective:
        case "all_reach_exit":
            return all(a.first_exit_tick is not None for a in agents)
        case "first_exit":
            return any(a.first_exit_tick is not None for a in agents)
        case "all_at_exit_simultaneously":
            return all(a.position == maze.exit for a in agents)


def resolve(
    maze: MazeDefinition, rules: RulesConfig, state: WorldState, submissions: Mapping[AgentId, Submission]
) -> TickResult:
    """Resolve tick `state.tick + 1`. A missing submission is a timeout."""
    tick = state.tick + 1
    agents: list[AgentState] = []
    events: list[GameEvent] = []
    radio_batch: list[RadioObservation] = []

    for prev in state.agents:
        sub = submissions.get(prev.agent_id) or Submission(action=None, failure="timeout")
        new_agent, agent_events, radio = _resolve_agent(maze, rules, prev, sub, tick)
        agents.append(new_agent)
        events.extend(agent_events)
        if radio is not None:
            radio_batch.append(radio)

    for msg in radio_batch:
        events.append(
            RadioSent(
                sender=msg.sender,
                sent_tick=tick,
                visible_decision_tick=tick + 1,
                recipients=[a for a in AGENT_IDS if a != msg.sender],
                text=msg.text,
                utf8_bytes=utf8_len(msg.text),
            )
        )

    meetings = meeting_groups(agents)
    for group in meetings:
        position = next(a.position for a in agents if a.agent_id == group[0])
        events.append(MeetingObserved(agents=group, position=position))
    for prev, new in zip(state.agents, agents, strict=True):
        if prev.first_exit_tick is None and new.first_exit_tick is not None:
            events.append(ExitReached(agent_id=new.agent_id, tick=tick))

    met_tick = state.objective_met_tick
    if met_tick is None and _objective_met(maze, rules, agents):
        met_tick = tick

    new_state = WorldState(
        tick=tick, agents=agents, radio_batch=radio_batch, meetings=meetings, objective_met_tick=met_tick
    )
    return TickResult(new_state, events)
