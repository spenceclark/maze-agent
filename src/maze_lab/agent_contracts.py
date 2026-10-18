"""Agent-facing wire contracts (spec §7).

Everything an agent sees or produces is defined here. Nothing in this module
may reference world coordinates, maze metadata, or spectator data.
"""

import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

AgentId = Literal["A", "B", "C"]
Direction = Literal["N", "E", "S", "W"]
Move = Literal["N", "E", "S", "W", "STAY"]
Edge = Literal["open", "interior_wall", "outer_brick"]
Objective = Literal["all_reach_exit", "first_exit", "all_at_exit_simultaneously"]

AGENT_IDS: tuple[AgentId, ...] = ("A", "B", "C")
OPPOSITE: dict[Direction, Direction] = {"N": "S", "S": "N", "E": "W", "W": "E"}

MAX_RAW_OUTPUT_BYTES = 64 * 1024

NotebookRejection = Literal[
    "stale_revision",
    "invalid_span",
    "invalid_unicode",
    "write_budget_exceeded",
    "notebook_cap_exceeded",
    "feature_disabled",
    "action_rejected",
    "conflicting_notebook_ops",
]
RadioRejection = Literal[
    "radio_cooldown",
    "radio_budget_exceeded",
    "empty_radio",
    "invalid_unicode",
    "feature_disabled",
    "action_rejected",
]
ForcedStayCause = Literal[
    "timeout", "provider_error", "refusal", "invalid_action", "stale_tick", "stay_disabled"
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def utf8_len(text: str) -> int:
    """UTF-8 byte length. Raises UnicodeEncodeError on lone surrogates."""
    return len(text.encode("utf-8"))


class Notebook(Contract):
    owner: AgentId
    revision: int = Field(ge=0)
    text: str
    utf8_bytes: int = Field(ge=0)
    codepoints: int = Field(ge=0)

    @classmethod
    def of(cls, owner: AgentId, revision: int, text: str) -> Self:
        return cls(owner=owner, revision=revision, text=text, utf8_bytes=utf8_len(text), codepoints=len(text))

    @model_validator(mode="after")
    def _lengths_match_text(self) -> Self:
        if self.utf8_bytes != utf8_len(self.text) or self.codepoints != len(self.text):
            raise ValueError("notebook lengths do not match text")
        return self


class NotebookEdit(Contract):
    expected_revision: int = Field(ge=0)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str


class TurnAction(Contract):
    schema_version: Literal["1.0"]
    tick: int = Field(ge=1)
    move: Move
    notebook_edit: NotebookEdit | None
    radio: str | None


class SimpleTurnAction(Contract):
    """Action variant for `notebook_ops="append_rewrite"` (not in spec §7, a declared rules variant).

    The engine places the text itself, so agents never compute offsets or revisions.
    An empty string counts as no change; setting both fields rejects the notebook component.
    """

    schema_version: Literal["1.1"]
    tick: int = Field(ge=1)
    move: Move
    notebook_append: str | None  # added to the end of the notebook
    notebook_rewrite: str | None  # replaces the whole notebook
    radio: str | None


AnyTurnAction = Annotated[TurnAction | SimpleTurnAction, Field(discriminator="schema_version")]
NotebookOps = Literal["splice", "append_rewrite"]
ACTION_MODELS: dict[NotebookOps, type[TurnAction] | type[SimpleTurnAction]] = {
    "splice": TurnAction,
    "append_rewrite": SimpleTurnAction,
}


class LocalCell(Contract):
    north: Edge
    east: Edge
    south: Edge
    west: Edge
    is_exit: bool
    landmarks: list[str]
    checkpoints: list[str]


class PeerRange(Contract):
    agent_id: AgentId
    distance_tenths: int = Field(ge=0)


class RadioObservation(Contract):
    sender: AgentId
    sent_tick: int = Field(ge=1)
    text: str


class MovementReceipt(Contract):
    attempted: Move | None
    outcome: Literal["spawned", "moved", "blocked", "stayed", "forced_stay"]
    arrived_from: Direction | None
    cause: str | None

    @model_validator(mode="after")
    def _arrival_only_when_moved(self) -> Self:
        if self.outcome == "moved":
            if self.attempted in (None, "STAY") or self.arrived_from != OPPOSITE[self.attempted]:
                raise ValueError("arrived_from must be the opposite of the attempted direction")
        elif self.arrived_from is not None:
            raise ValueError("arrived_from is only present for outcome 'moved'")
        return self


class ComponentReceipt(Contract):
    status: Literal["not_requested", "accepted", "rejected"]
    code: str | None


NOT_REQUESTED = ComponentReceipt(status="not_requested", code=None)
ACCEPTED = ComponentReceipt(status="accepted", code=None)


class ActionReceipt(Contract):
    tick: int = Field(ge=0)
    movement: MovementReceipt
    notebook: ComponentReceipt
    radio: ComponentReceipt


SPAWN_RECEIPT = ActionReceipt(
    tick=0,
    movement=MovementReceipt(attempted=None, outcome="spawned", arrived_from=None, cause=None),
    notebook=NOT_REQUESTED,
    radio=NOT_REQUESTED,
)


class Budgets(Contract):
    notebook_cap_bytes: int = Field(ge=0)
    notebook_insert_bytes: int = Field(ge=0)
    radio_message_bytes: int = Field(ge=0)
    radio_next_eligible_tick: int = Field(ge=1)
    radio_enabled: bool
    notebook_enabled: bool
    allow_stay: bool


class Observation(Contract):
    schema_version: Literal["1.0"]
    agent_id: AgentId
    decision_tick: int = Field(ge=1)
    state_tick: int = Field(ge=0)
    has_reached_exit: bool
    local: LocalCell
    exit_distance_tenths: int = Field(ge=0)
    peer_ranges: list[PeerRange]
    last_action: ActionReceipt
    notebook: Notebook
    radio_inbox: list[RadioObservation]
    colocated_notebooks: list[Notebook]
    budgets: Budgets

    @model_validator(mode="after")
    def _invariants(self) -> Self:
        peers = [a for a in AGENT_IDS if a != self.agent_id]
        if self.decision_tick != self.state_tick + 1:
            raise ValueError("decision_tick must equal state_tick + 1")
        if self.last_action.tick != self.state_tick:
            raise ValueError("last_action.tick must equal state_tick")
        if [p.agent_id for p in self.peer_ranges] != peers:
            raise ValueError("peer_ranges must list both peers once, in ID order")
        if self.notebook.owner != self.agent_id:
            raise ValueError("notebook must belong to the observing agent")
        owners = [n.owner for n in self.colocated_notebooks]
        if len(set(owners)) != len(owners) or self.agent_id in owners:
            raise ValueError("colocated_notebooks must be distinct peers")
        if len(self.radio_inbox) > 2 or any(
            m.sender == self.agent_id or m.sent_tick != self.state_tick for m in self.radio_inbox
        ):
            raise ValueError("radio_inbox holds at most the peers' messages from state_tick")
        return self


class AgentRules(Contract):
    """Public rules shown to every agent. Never a serialization of RunConfig."""

    version: str
    agent_ids: list[AgentId]
    objective: Objective
    allow_stay: bool
    notebook_enabled: bool
    notebook_cap_bytes: int = Field(ge=0)
    notebook_insert_bytes: int = Field(ge=0)
    radio_enabled: bool
    radio_message_bytes: int = Field(ge=0)
    radio_cooldown_ticks: int = Field(ge=0)
    meeting_notebooks_enabled: bool
    checkpoint_labels: list[str]
    max_provider_requests_per_turn: int = Field(ge=1)
    landmarks_enabled: bool = False  # positions and labels are never public
    notebook_ops: NotebookOps = "splice"


class InvalidActionError(ValueError):
    """Raw model output could not be accepted as a TurnAction."""


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise InvalidActionError("duplicate JSON key")
    return dict(pairs)


def _reject_constant(name: str) -> object:
    raise InvalidActionError(f"non-finite number {name}")


def _check_strings_encodable(value: object) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as e:
            raise InvalidActionError("invalid Unicode surrogate") from e
    elif isinstance(value, dict):
        for k, v in value.items():
            _check_strings_encodable(k)
            _check_strings_encodable(v)
    elif isinstance(value, list):
        for v in value:
            _check_strings_encodable(v)


def parse_turn_action(raw: str, notebook_ops: NotebookOps = "splice") -> TurnAction | SimpleTurnAction:
    """Strictly parse one complete JSON object into the run's action model (spec §7).

    Rejects oversized output, duplicate keys, NaN/Infinity, lone surrogates,
    trailing prose, and extra fields. Raises InvalidActionError.
    """
    try:
        if utf8_len(raw) > MAX_RAW_OUTPUT_BYTES:
            raise InvalidActionError("raw output exceeds 64 KiB")
        parsed = json.loads(raw, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
    except UnicodeEncodeError as e:
        raise InvalidActionError("invalid Unicode surrogate") from e
    except json.JSONDecodeError as e:
        raise InvalidActionError(f"malformed JSON: {e.msg}") from e
    if not isinstance(parsed, dict):
        raise InvalidActionError("top-level JSON value must be an object")
    _check_strings_encodable(parsed)
    try:
        return ACTION_MODELS[notebook_ops].model_validate_json(raw)
    except ValueError as e:
        raise InvalidActionError(str(e)) from e
