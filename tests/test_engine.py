"""Reducer acceptance cases from spec §17, named after the table rows."""

from helpers import RULES, P, act, grid, step

from maze_lab.agent_contracts import AGENT_IDS, AgentId, Notebook
from maze_lab.config import RulesConfig
from maze_lab.domain.events import RadioSent
from maze_lab.domain.reducer import Submission, resolve
from maze_lab.domain.state import WorldState, initial_state
from maze_lab.observation import observe

# 3x3 open grid. Exit bottom-right; A top-left, B top-middle, C middle-left.
OPEN = grid(3, 3, exit=P(2, 2), spawns=[P(0, 0), P(1, 0), P(0, 1)])


def start(maze=OPEN) -> WorldState:
    return initial_state(maze)


def run_until(state: WorldState, tick: int, maze=OPEN) -> WorldState:
    while state.tick < tick:
        state = step(maze, state).state
    return state


def test_successful_east_move():
    s1 = step(OPEN, start(), A=act(1, "E")).state
    a = s1.agent("A")
    assert a.position == P(1, 0) and a.successful_moves == 1
    receipt = observe(OPEN, RULES, s1, "A").last_action
    assert (receipt.movement.attempted, receipt.movement.outcome, receipt.movement.arrived_from) == (
        "E",
        "moved",
        "W",
    )
    assert a.notebook.revision == 0 and a.notebook.text == ""


def test_blocked_east_move_still_applies_note_and_radio():
    # A at (0,0) has a wall to the east; only south is open.
    maze = grid(
        2,
        2,
        P(1, 1),
        [P(0, 0), P(1, 0), P(0, 1)],
        open_edges=[(P(0, 0), "S"), (P(0, 1), "E"), (P(1, 0), "S")],
    )
    s1 = step(maze, start(maze), A=act(1, "E", edit=(0, 0, 0, "east is a wall"), radio="hello")).state
    a = s1.agent("A")
    assert a.position == P(0, 0)
    assert a.last_receipt.movement.model_dump() == {
        "attempted": "E",
        "outcome": "blocked",
        "arrived_from": None,
        "cause": "wall",
    }
    assert a.last_receipt.notebook.status == "accepted" and a.notebook.text == "east is a wall"
    assert a.last_receipt.radio.status == "accepted"


def test_turn_10_transmission_visible_once_with_cooldown():
    s9 = run_until(start(), 9)
    s10 = step(OPEN, s9, A=act(10, radio="exit is south")).state
    assert [m.text for m in observe(OPEN, RULES, s10, "B").radio_inbox] == ["exit is south"]
    assert [m.text for m in observe(OPEN, RULES, s10, "C").radio_inbox] == ["exit is south"]
    assert observe(OPEN, RULES, s10, "A").radio_inbox == []  # sender gets no copy
    assert observe(OPEN, RULES, s10, "A").budgets.radio_next_eligible_tick == 16

    state = s10
    for t in range(11, 16):
        state = step(OPEN, state, A=act(t, radio="again")).state
        assert state.agent("A").last_receipt.radio.code == "radio_cooldown"
        assert state.radio_batch == []
    s16 = step(OPEN, state, A=act(16, radio="again")).state
    assert s16.agent("A").last_receipt.radio.status == "accepted"


def test_recipient_times_out_on_11_message_expires_but_archive_keeps_it():
    s9 = run_until(start(), 9)
    s10, events10 = step(OPEN, s9, A=act(10, radio="ping"))
    assert any(isinstance(e, RadioSent) and e.text == "ping" for e in events10)
    s11 = resolve(OPEN, RULES, s10, {"A": act(11), "C": act(11)})  # B missing: timeout
    assert s11.state.agent("B").last_receipt.movement.cause == "timeout"
    assert observe(OPEN, RULES, s11.state, "B").radio_inbox == []


def test_two_agents_swap_cells_do_not_meet():
    s1 = step(OPEN, start(), A=act(1, "E"), B=act(1, "W")).state
    assert s1.agent("A").position == P(1, 0) and s1.agent("B").position == P(0, 0)
    assert s1.meetings == []
    assert observe(OPEN, RULES, s1, "A").colocated_notebooks == []


def test_two_agents_converge_see_post_edit_notebooks():
    s1 = step(
        OPEN, start(), A=act(1, "E", edit=(0, 0, 0, "A was here")), B=act(1, edit=(0, 0, 0, "B notes"))
    ).state
    assert s1.meetings == [["A", "B"]]
    seen_by_a = observe(OPEN, RULES, s1, "A").colocated_notebooks
    seen_by_b = observe(OPEN, RULES, s1, "B").colocated_notebooks
    assert seen_by_a == [Notebook.of("B", 1, "B notes")]
    assert seen_by_b == [Notebook.of("A", 1, "A was here")]
    assert observe(OPEN, RULES, s1, "C").colocated_notebooks == []


def test_all_three_converge_each_sees_two_books_and_own_unchanged():
    maze = grid(3, 3, P(0, 0), [P(0, 1), P(1, 0), P(2, 1)])
    s1 = step(maze, start(maze), A=act(1, "E"), B=act(1, "S"), C=act(1, "W")).state
    assert s1.meetings == [["A", "B", "C"]]
    for agent in AGENT_IDS:
        obs = observe(maze, RULES, s1, agent)
        assert [n.owner for n in obs.colocated_notebooks] == [a for a in "ABC" if a != agent]
        assert obs.notebook.revision == 0


def test_meeting_then_separation():
    s1 = step(OPEN, start(), A=act(1, "E")).state
    assert observe(OPEN, RULES, s1, "A").colocated_notebooks != []  # visible for the departure decision
    s2 = step(OPEN, s1, A=act(2, "S")).state
    assert observe(OPEN, RULES, s2, "A").colocated_notebooks == []
    assert observe(OPEN, RULES, s2, "B").colocated_notebooks == []


def test_oversized_or_stale_notebook_edit_rejected_movement_unaffected():
    s1 = step(OPEN, start(), A=act(1, "S", edit=(5, 0, 0, "stale"))).state
    assert s1.agent("A").last_receipt.notebook.code == "stale_revision"
    assert s1.agent("A").position == P(0, 1)

    s2 = step(OPEN, s1, A=act(2, "N", edit=(0, 0, 0, "x" * 1025))).state
    assert s2.agent("A").last_receipt.notebook.code == "write_budget_exceeded"
    assert s2.agent("A").notebook == Notebook.of("A", 0, "")
    assert s2.agent("A").position == P(0, 0)

    s3 = step(OPEN, s2, A=act(3, edit=(0, 1, 2, "x"))).state
    assert s3.agent("A").last_receipt.notebook.code == "invalid_span"


def test_notebook_cap_exceeded_never_truncates():
    rules = RulesConfig(notebook_cap_bytes=10, notebook_insert_bytes=1024)
    state = step(OPEN, start(), rules, A=act(1, edit=(0, 0, 0, "123456789"))).state
    state = step(OPEN, state, rules, A=act(2, edit=(1, 9, 9, "ab"))).state
    assert state.agent("A").last_receipt.notebook.code == "notebook_cap_exceeded"
    assert state.agent("A").notebook.text == "123456789"


def test_multibyte_utf8_uses_bytes_for_caps_and_codepoints_for_offsets():
    emoji = "\N{GRINNING FACE}"  # 4 UTF-8 bytes, 1 code point
    state = step(OPEN, start(), A=act(1, edit=(0, 0, 0, emoji * 256))).state  # exactly 1024 bytes
    assert state.agent("A").last_receipt.notebook.status == "accepted"
    assert state.agent("A").notebook.utf8_bytes == 1024 and state.agent("A").notebook.codepoints == 256

    state = step(OPEN, state, A=act(2, edit=(1, 1, 1, "é"))).state  # between first and second emoji
    assert state.agent("A").notebook.text == emoji + "é" + emoji * 255

    state = step(OPEN, state, A=act(3, edit=(2, 0, 0, emoji * 257))).state
    assert state.agent("A").last_receipt.notebook.code == "write_budget_exceeded"


def test_full_notebook_compaction_is_one_revision():
    state = start()
    for t in range(1, 9):
        rev = state.agent("A").notebook.revision
        end = state.agent("A").notebook.codepoints
        state = step(OPEN, state, A=act(t, edit=(rev, end, end, "y" * 1024))).state
    assert state.agent("A").notebook.utf8_bytes == 8192
    full = state.agent("A").notebook
    state = step(OPEN, state, A=act(9, edit=(full.revision, 0, full.codepoints, "summary"))).state
    assert state.agent("A").notebook == Notebook.of("A", full.revision + 1, "summary")


def test_redundant_valid_splice_still_increments_revision():
    state = step(OPEN, start(), A=act(1, edit=(0, 0, 0, ""))).state
    assert state.agent("A").notebook.revision == 1


def test_invalid_action_or_wrong_tick_is_forced_noop():
    s1, events = step(OPEN, start(), A=act(7, "E", edit=(0, 0, 0, "hidden"), radio="hidden"))
    a = s1.agent("A")
    assert a.position == P(0, 0)
    assert a.last_receipt.movement.outcome == "forced_stay" and a.last_receipt.movement.cause == "stale_tick"
    assert a.notebook.revision == 0 and s1.radio_batch == []
    assert a.last_receipt.notebook.code == "action_rejected"
    assert not any(isinstance(e, RadioSent) for e in events)

    failed = Submission(action=None, failure="invalid_action")
    s2 = step(OPEN, s1, A=failed).state
    assert s2.agent("A").last_receipt.movement.model_dump() == {
        "attempted": None,
        "outcome": "forced_stay",
        "arrived_from": None,
        "cause": "invalid_action",
    }


def test_distinct_response_orders_give_identical_state_and_events():
    subs: dict[AgentId, Submission] = {
        "A": act(1, "E", radio="a"),
        "B": act(1, "S", edit=(0, 0, 0, "b")),
        "C": act(1, "E", radio="c"),
    }
    forward = resolve(OPEN, RULES, start(), subs)
    backward = resolve(OPEN, RULES, start(), dict(reversed(list(subs.items()))))
    assert forward == backward
    assert [e.sender for e in forward.events if isinstance(e, RadioSent)] == ["A", "C"]


def test_stay_disabled_rejects_only_movement():
    rules = RulesConfig(allow_stay=False)
    s1 = step(OPEN, start(), rules, A=act(1, "STAY", edit=(0, 0, 0, "note"))).state
    assert s1.agent("A").last_receipt.movement.cause == "stay_disabled"
    assert s1.agent("A").notebook.text == "note"


def test_disabled_features_reject_with_feature_disabled():
    rules = RulesConfig(
        notebook_enabled=False,
        notebook_cap_bytes=0,
        notebook_insert_bytes=0,
        radio_enabled=False,
        radio_message_bytes=0,
    )
    s1 = step(OPEN, start(), rules, A=act(1, edit=(0, 0, 0, "x"), radio="x")).state
    assert s1.agent("A").last_receipt.notebook.code == "feature_disabled"
    assert s1.agent("A").last_receipt.radio.code == "feature_disabled"


def test_radio_whitespace_and_byte_budget():
    s1 = step(OPEN, start(), A=act(1, radio="  \n"), B=act(1, radio="é" * 141)).state
    assert s1.agent("A").last_receipt.radio.code == "empty_radio"
    assert s1.agent("B").last_receipt.radio.code == "radio_budget_exceeded"
    s2 = step(OPEN, s1, A=act(2, radio="é" * 140)).state  # 280 bytes exactly; failures did not start cooldown
    assert s2.agent("A").last_receipt.radio.status == "accepted"


def test_final_tick_success_is_recorded_on_resolving_tick():
    maze = grid(2, 2, P(1, 1), [P(0, 1), P(1, 0), P(0, 0)])
    s1 = step(maze, start(maze), A=act(1, "E"), B=act(1, "S")).state
    assert s1.objective_met_tick is None
    assert s1.agent("A").first_exit_tick == 1 and s1.agent("B").first_exit_tick == 1
    s2 = step(maze, s1, A=act(2, "N"), C=act(2, "E")).state
    s3 = step(maze, s2, C=act(3, "S")).state
    assert s3.objective_met_tick == 3
    assert s3.agent("A").first_exit_tick == 1  # earlier visit still counts after leaving
