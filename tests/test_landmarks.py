"""Landmarks: seeded placement, local visibility, public rules (spec §4.4)."""

import json

import pytest
from helpers import HAND_AUTHORED, RULES, P, act, grid, step
from pydantic import ValidationError

from maze_lab.config import LANDMARK_LABELS, MazeSettings, RulesConfig
from maze_lab.domain.generator import generate_maze
from maze_lab.domain.maze import Landmark, build_maze
from maze_lab.domain.state import initial_state
from maze_lab.hashing import content_hash
from maze_lab.observation import observe, public_rules
from maze_lab.policies.prompt import system_instruction


def test_placement_is_seeded_distinct_and_leaves_the_maze_unchanged():
    plain = generate_maze(7, 12, 12)
    marked = generate_maze(7, 12, 12, landmark_count=10)
    assert (marked.cells, marked.exit, marked.spawns) == (plain.cells, plain.exit, plain.spawns)
    assert len(marked.landmarks) == 10
    assert len({lm.position for lm in marked.landmarks}) == 10
    assert len({lm.label for lm in marked.landmarks}) == 10
    assert all(lm.label in LANDMARK_LABELS for lm in marked.landmarks)
    assert marked == generate_maze(7, 12, 12, landmark_count=10)
    assert marked.landmarks != generate_maze(8, 12, 12, landmark_count=10).landmarks


def test_landmark_free_mazes_keep_their_pre_landmark_hash():
    maze = generate_maze(3, 6, 6)
    legacy = content_hash(maze.model_dump(mode="json", exclude={"maze_hash", "landmarks"}))
    assert maze.maze_hash == legacy


def test_landmark_is_visible_only_on_its_own_cell():
    base = grid(3, 3, P(2, 2), [P(0, 0), P(1, 0), P(0, 1)])
    maze = build_maze(
        3,
        3,
        [
            (c, d)
            for c in (P(x, y) for y in range(3) for x in range(3))
            for d in ("E", "S")
            if (c.x < 2 if d == "E" else c.y < 2)
        ],
        base.exit,
        base.spawns,
        HAND_AUTHORED,
        [Landmark(position=P(1, 0), label="clock")],
    )
    state = initial_state(maze)
    assert observe(maze, RULES, state, "B").local.landmarks == ["clock"]  # B spawns on it
    assert observe(maze, RULES, state, "A").local.landmarks == []
    moved = step(maze, state, A=act(1, "E"), B=act(1, "S")).state
    assert observe(maze, RULES, moved, "A").local.landmarks == ["clock"]
    assert observe(maze, RULES, moved, "B").local.landmarks == []
    # positions never leak into the observation
    assert '"position"' not in json.dumps(observe(maze, RULES, moved, "A").model_dump(mode="json"))


def test_duplicate_landmark_labels_are_rejected():
    with pytest.raises(ValidationError, match="distinct"):
        build_maze(
            2,
            2,
            [(P(0, 0), "E"), (P(0, 0), "S"), (P(1, 0), "S")],
            P(1, 1),
            [P(0, 0), P(1, 0), P(0, 1)],
            HAND_AUTHORED,
            [Landmark(position=P(0, 0), label="owl"), Landmark(position=P(1, 0), label="owl")],
        )


def test_landmark_count_is_bounded_by_the_label_vocabulary():
    MazeSettings(landmark_count=len(LANDMARK_LABELS))
    with pytest.raises(ValidationError):
        MazeSettings(landmark_count=len(LANDMARK_LABELS) + 1)


def test_rules_mention_landmarks_only_when_enabled():
    assert "landmark" not in system_instruction(public_rules(RulesConfig()), "A")
    text = system_instruction(public_rules(RulesConfig(), landmarks_enabled=True), "A")
    assert "local.landmarks" in text and "unique and fixed to one cell" in text
