"""The append-log notebook variant: a rolling log the engine maintains (rules.notebook_ops)."""

import json

import pytest
from helpers import P, grid

from maze_lab.agent_contracts import (
    AGENT_IDS,
    AgentId,
    AppendTurnAction,
    InvalidActionError,
    Notebook,
    TurnAction,
    parse_turn_action,
)
from maze_lab.config import RulesConfig
from maze_lab.domain.events import DecisionResolved, NotebookUpdated
from maze_lab.domain.reducer import Submission, resolve
from maze_lab.domain.state import WorldState, initial_state
from maze_lab.observation import observe, public_rules
from maze_lab.policies.prompt import system_instruction, user_blocks

MAZE = grid(3, 3, P(2, 2), [P(0, 0), P(1, 0), P(0, 1)])
RULES = RulesConfig(notebook_ops="append_log")


def note(tick: int, text: str | None = None, move: str = "STAY") -> Submission:
    action = AppendTurnAction.model_validate(
        {"schema_version": "1.2", "tick": tick, "move": move, "notebook_append": text, "radio": None}
    )
    return Submission(action=action, failure=None)


def play(state: WorldState, rules: RulesConfig = RULES, **subs: Submission) -> WorldState:
    t = state.tick + 1
    stay: dict[AgentId, Submission] = {a: subs.get(a, note(t)) for a in AGENT_IDS}
    return resolve(MAZE, rules, state, stay).state


def test_notes_are_appended_on_new_lines():
    s = play(initial_state(MAZE), A=note(1, "first", move="E"))
    s = play(s, A=note(2, "second"))
    assert s.agent("A").notebook == Notebook.of("A", 2, "first\nsecond")
    assert s.agent("A").position == P(1, 0)  # the move happens alongside the note


def test_oldest_lines_drop_off_when_the_cap_would_be_exceeded():
    rules = RulesConfig(notebook_ops="append_log", notebook_cap_bytes=12, notebook_insert_bytes=8)
    s = play(initial_state(MAZE), rules, A=note(1, "aaaa"))
    s = play(s, rules, A=note(2, "bbbb"))
    result = resolve(MAZE, rules, s, {a: note(3, "cccc" if a == "A" else None) for a in AGENT_IDS})
    assert result.state.agent("A").notebook.text == "bbbb\ncccc"
    (update,) = [e for e in result.events if isinstance(e, NotebookUpdated)]
    assert update.splice.text == "\ncccc" and update.dropped_codepoints == 5  # "aaaa\n"


def test_a_note_over_the_write_budget_is_rejected_whole():
    rules = RulesConfig(notebook_ops="append_log", notebook_cap_bytes=12, notebook_insert_bytes=8)
    s = play(initial_state(MAZE), rules, A=note(1, "x" * 9))
    assert s.agent("A").last_receipt.notebook.code == "write_budget_exceeded"
    assert s.agent("A").notebook.revision == 0


def test_blank_and_null_notes_mean_no_change():
    s = play(initial_state(MAZE), A=note(1, "keep me"))
    for i, blank in enumerate(["", "  ", "null", " NULL "], start=2):
        s = play(s, A=note(i, blank))
        assert s.agent("A").last_receipt.notebook.status == "not_requested"
    assert s.agent("A").notebook == Notebook.of("A", 1, "keep me")


def test_parser_uses_the_runs_action_model():
    raw = json.dumps(
        {"schema_version": "1.2", "tick": 1, "move": "N", "notebook_append": "hi", "radio": None}
    )
    assert isinstance(parse_turn_action(raw, "append_log"), AppendTurnAction)
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


def test_append_log_prompts_show_notebooks_as_plain_text():
    obs = observe(MAZE, RULES, play(initial_state(MAZE), A=note(1, 'line {"a": 1}')), "A")
    own, peers, rest = user_blocks(obs, "append_log")
    assert own.endswith('<<<NOTEBOOK A\nline {"a": 1}\nNOTEBOOK A>>>')
    assert '"owner"' not in own and '"revision"' not in own
    assert peers.endswith("(none)") and '"owner"' not in rest
    text = system_instruction(public_rules(RULES), "A")
    assert "rolling log" in text and "notebook_rewrite" not in text and '"1.2"' in text
