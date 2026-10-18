"""Information-boundary audits for the observation projection (spec §4.2, §17)."""

import json

from helpers import RULES, P, act, grid, step

from maze_lab.agent_contracts import AGENT_IDS, AgentRules, Observation
from maze_lab.config import RulesConfig
from maze_lab.domain.generator import generate_maze
from maze_lab.domain.state import initial_state
from maze_lab.observation import observe, public_rules
from maze_lab.policies.prompt import system_instruction, user_blocks

FORBIDDEN_KEYS = {
    "x",
    "y",
    "position",
    "width",
    "height",
    "seed",
    "root_seed",
    "maze_hash",
    "generator",
    "cells",
}


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _all_keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _all_keys(v)}
    return set()


def test_observation_contains_no_spectator_metadata():
    maze = generate_maze(42, 15, 15)
    state = initial_state(maze)
    for agent in AGENT_IDS:
        obs = observe(maze, RULES, state, agent)
        assert _all_keys(json.loads(obs.model_dump_json())).isdisjoint(FORBIDDEN_KEYS)
    rules_keys = set(AgentRules.model_fields)
    assert rules_keys.isdisjoint(FORBIDDEN_KEYS | {"condition", "agents", "timing", "model"})


def test_initial_observation_shape():
    maze = grid(3, 3, P(2, 2), [P(0, 0), P(2, 0), P(0, 2)])
    obs = observe(maze, RULES, initial_state(maze), "B")
    assert (obs.decision_tick, obs.state_tick) == (1, 0)
    assert obs.last_action.movement.outcome == "spawned"
    assert obs.peer_ranges is not None
    assert [(p.agent_id, p.distance_tenths) for p in obs.peer_ranges] == [("A", 20), ("C", 28)]
    assert obs.exit_distance_tenths == 20
    assert (obs.local.north, obs.local.east, obs.local.south, obs.local.west) == (
        "outer_brick",
        "outer_brick",
        "open",
        "open",
    )
    assert obs.budgets.radio_next_eligible_tick == 1


def test_observation_round_trips_through_strict_json():
    maze = grid(3, 3, P(2, 2), [P(0, 0), P(1, 0), P(0, 1)])
    state = step(maze, initial_state(maze), A=act(1, "E", edit=(0, 0, 0, "hi"), radio="yo")).state
    obs = observe(maze, RULES, state, "B")
    assert Observation.model_validate_json(obs.model_dump_json()) == obs


def test_public_rules_projection():
    rules = public_rules(RULES)
    assert rules.agent_ids == ["A", "B", "C"] and rules.max_provider_requests_per_turn == 1


def test_distance_sensors_off_leaves_distances_out():
    maze = grid(3, 3, P(2, 2), [P(0, 0), P(2, 0), P(0, 2)])
    off = RulesConfig(distance_sensors="none")
    obs = observe(maze, off, initial_state(maze), "B")
    assert obs.exit_distance_tenths is None and obs.peer_ranges is None
    text = "".join(user_blocks(obs))
    assert "exit_distance_tenths" not in text and "peer_ranges" not in text
    rules = system_instruction(public_rules(off), "B")
    assert "no distance sensors" in rules and "Euclidean" not in rules
    assert "Euclidean" in system_instruction(public_rules(RULES), "B")
