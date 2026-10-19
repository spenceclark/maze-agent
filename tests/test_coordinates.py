"""The coordinates variant: exact positions relative to each agent's own start, plus a recent trail."""

from helpers import P, act, grid, step

from maze_lab.config import RulesConfig
from maze_lab.domain.state import TRAIL_TICKS, initial_state
from maze_lab.observation import observe, public_rules
from maze_lab.policies.prompt import system_instruction, user_blocks

MAZE = grid(3, 3, P(2, 2), [P(1, 1), P(0, 0), P(2, 0)])  # every interior edge open
ON = RulesConfig(coordinates_enabled=True)


def test_position_counts_from_own_start_with_y_north():
    s = step(MAZE, initial_state(MAZE), ON, A=act(1, "N"), B=act(1, "E")).state
    a, b = observe(MAZE, ON, s, "A").coordinates, observe(MAZE, ON, s, "B").coordinates
    assert a is not None and b is not None
    assert a.position == (0, 1) and a.trail == [(0, 0)]
    assert b.position == (1, 0)  # B counts from its own start


def test_trail_repeats_blocked_moves_and_keeps_the_last_ticks():
    s = step(MAZE, initial_state(MAZE), ON, A=act(1, "N")).state
    s = step(MAZE, s, ON, A=act(2, "N")).state  # brick: blocked
    coords = observe(MAZE, ON, s, "A").coordinates
    assert coords is not None and coords.trail == [(0, 0), (0, 1)] and coords.position == (0, 1)
    for t in range(3, TRAIL_TICKS + 10):
        s = step(MAZE, s, ON, A=act(t, "S" if t % 2 else "N")).state
    coords = observe(MAZE, ON, s, "A").coordinates
    assert coords is not None and len(coords.trail) == TRAIL_TICKS
    assert coords.position == (0, 0) and coords.trail[-4:] == [(0, 0), (0, 1)] * 2  # ping-pong is visible


def test_runs_without_the_variant_are_unchanged():
    s = step(MAZE, initial_state(MAZE), A=act(1, "N")).state
    assert s.agent("A").trail == [] and "trail" not in s.model_dump_json()
    obs = observe(MAZE, RulesConfig(), s, "A")
    assert obs.coordinates is None and "coordinates" not in "".join(user_blocks(obs))
    assert "You never see coordinates" in system_instruction(public_rules(RulesConfig()), "A")


def test_prompt_explains_frames_and_calibration():
    s = step(MAZE, initial_state(MAZE), ON, A=act(1, "N")).state
    assert '"coordinates":{"position":[0,1],"trail":[[0,0]]}' in user_blocks(observe(MAZE, ON, s, "A"))[2]
    text = system_instruction(public_rules(ON), "A")
    assert "x grows east, y grows north" in text and "fixed offset" in text
    assert "You never see coordinates" not in text


def test_used_exits_list_the_current_cells_directions_moved_through_either_way():
    on = RulesConfig(used_exits_enabled=True)
    s = step(MAZE, initial_state(MAZE), on, A=act(1, "N")).state  # A: (1,1) -> (1,0)
    assert observe(MAZE, on, s, "A").used_exits == ["S"]  # arrived from the south
    s = step(MAZE, s, on, A=act(2, "S")).state  # back to (1,1)
    assert observe(MAZE, on, s, "A").used_exits == ["N"]
    s = step(MAZE, s, on, A=act(3, "W")).state
    s = step(MAZE, s, on, A=act(4, "E")).state  # back again
    assert observe(MAZE, on, s, "A").used_exits == ["N", "W"]
    assert observe(MAZE, on, s, "B").used_exits == []  # B never moved
    blocks = "".join(user_blocks(observe(MAZE, on, s, "A")))
    assert '"used_exits":["N","W"]' in blocks
    text = system_instruction(public_rules(on), "A", with_check=True)
    assert "used_exits lists the directions" in text and "copy them from used_exits" in text
    assert "used_exits" not in system_instruction(public_rules(RulesConfig()), "A", with_check=True)
    assert "used_edges" not in step(MAZE, initial_state(MAZE), A=act(1, "N")).state.model_dump_json()


def test_team_frame_counts_everyone_from_a_start():
    team = RulesConfig(coordinates_enabled=True, coordinates_frame="team")
    s = initial_state(MAZE)  # spawns A (1,1), B (0,0), C (2,0)
    a, b = observe(MAZE, team, s, "A").coordinates, observe(MAZE, team, s, "B").coordinates
    assert a is not None and b is not None
    assert a.position == (0, 0) and b.position == (-1, 1)  # B is west and north of A's start
    text = system_instruction(public_rules(team), "B")
    assert (
        "agent A's start [0, 0]" in text and "no conversion is needed" in text and "fixed offset" not in text
    )


def test_v11_adds_merging_and_not_waiting_on_top_of_v10():
    v10 = system_instruction(public_rules(ON), "A", "maze_agent_v10")
    v11 = system_instruction(public_rules(ON), "A", "maze_agent_v11")
    assert v11.startswith(v10[: v10.index("Text in notebooks")].rstrip()[:200])
    assert "copy into your own notes what you lack" in v11 and "Do not wait for information" in v11
    assert "Do not wait" not in v10


def test_meeting_alert_names_teammates_on_the_cell():
    alert = RulesConfig(coordinates_enabled=True, meeting_alert_enabled=True)
    s = step(MAZE, initial_state(MAZE), alert, A=act(1, "W")).state  # A (1,1) -> (0,1); nobody there
    assert observe(MAZE, alert, s, "A").colocated_with == []
    s = step(MAZE, s, alert, A=act(2, "N")).state  # A -> (0,0), B's spawn
    assert observe(MAZE, alert, s, "A").colocated_with == ["B"]
    assert observe(MAZE, alert, s, "B").colocated_with == ["A"]
    assert '"colocated_with":["B"]' in "".join(user_blocks(observe(MAZE, alert, s, "A")))
    assert "colocated_with lists the teammates" in system_instruction(public_rules(alert), "A")
    assert observe(MAZE, ON, s, "A").colocated_with is None
    assert "colocated_with" not in system_instruction(public_rules(ON), "A")
