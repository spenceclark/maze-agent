"""The append/rewrite notebook variant: the engine places the text (rules.notebook_ops)."""

import json

import pytest
from helpers import P, grid

from maze_lab.agent_contracts import (
    AGENT_IDS,
    AgentId,
    InvalidActionError,
    Notebook,
    SimpleTurnAction,
    TurnAction,
    parse_turn_action,
)
from maze_lab.config import RulesConfig
from maze_lab.domain.events import DecisionResolved
from maze_lab.domain.reducer import Submission, resolve
from maze_lab.domain.state import WorldState, initial_state

MAZE = grid(3, 3, P(2, 2), [P(0, 0), P(1, 0), P(0, 1)])
RULES = RulesConfig(notebook_ops="append_rewrite")


def simple(
    tick: int, append: str | None = None, rewrite: str | None = None, move: str = "STAY"
) -> Submission:
    action = SimpleTurnAction.model_validate(
        {
            "schema_version": "1.1",
            "tick": tick,
            "move": move,
            "notebook_append": append,
            "notebook_rewrite": rewrite,
            "radio": None,
        }
    )
    return Submission(action=action, failure=None)


def play(state: WorldState, rules: RulesConfig = RULES, **subs: Submission) -> WorldState:
    t = state.tick + 1
    stay: dict[AgentId, Submission] = {a: subs.get(a, simple(t)) for a in AGENT_IDS}
    return resolve(MAZE, rules, state, stay).state


def test_append_and_rewrite_need_no_offsets_or_revisions():
    s = play(initial_state(MAZE), A=simple(1, append="first. "))
    s = play(s, A=simple(2, append="second."))
    assert s.agent("A").notebook == Notebook.of("A", 2, "first. second.")
    s = play(s, A=simple(3, rewrite="summary"))
    assert s.agent("A").notebook == Notebook.of("A", 3, "summary")


def test_both_ops_reject_only_the_notebook_component():
    s = play(initial_state(MAZE), A=simple(1, append="x", rewrite="y", move="E"))
    a = s.agent("A")
    assert a.last_receipt.notebook.code == "conflicting_notebook_ops" and a.notebook.revision == 0
    assert a.position == P(1, 0)  # the move still happened


def test_budgets_and_cap_still_apply():
    rules = RulesConfig(notebook_ops="append_rewrite", notebook_cap_bytes=10, notebook_insert_bytes=8)
    s = play(initial_state(MAZE), rules, A=simple(1, append="x" * 9))
    assert s.agent("A").last_receipt.notebook.code == "write_budget_exceeded"
    s = play(s, rules, A=simple(2, append="12345678"))
    s = play(s, rules, A=simple(3, append="abc"))
    assert s.agent("A").last_receipt.notebook.code == "notebook_cap_exceeded"
    assert s.agent("A").notebook.text == "12345678"


def test_parser_uses_the_runs_action_model():
    raw = json.dumps(
        {
            "schema_version": "1.1",
            "tick": 1,
            "move": "N",
            "notebook_append": "hi",
            "notebook_rewrite": None,
            "radio": None,
        }
    )
    assert isinstance(parse_turn_action(raw, "append_rewrite"), SimpleTurnAction)
    with pytest.raises(InvalidActionError):
        parse_turn_action(raw)  # a splice run rejects the variant


def test_recorded_splice_decisions_still_load():
    old = DecisionResolved.model_validate_json(
        json.dumps(
            {
                "type": "agent.decision_resolved",
                "agent_id": "A",
                "invocation_id": None,
                "action": {
                    "schema_version": "1.0",
                    "tick": 1,
                    "move": "N",
                    "notebook_edit": None,
                    "radio": None,
                },
                "receipt": {
                    "tick": 1,
                    "movement": {"attempted": "N", "outcome": "moved", "arrived_from": "S", "cause": None},
                    "notebook": {"status": "not_requested", "code": None},
                    "radio": {"status": "not_requested", "code": None},
                },
            }
        )
    )
    assert isinstance(old.action, TurnAction)
