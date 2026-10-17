"""Maze generation properties and geometry (spec §4.1, §4.3, §16)."""

from math import floor, sqrt

import pytest
from helpers import HAND_AUTHORED, P, grid
from pydantic import ValidationError

from maze_lab.domain.generator import generate_maze
from maze_lab.domain.geometry import DIRECTIONS, distance_tenths
from maze_lab.domain.maze import build_maze
from maze_lab.domain.rng import SeededStream


@pytest.mark.parametrize("seed", range(200))
def test_generated_maze_is_a_perfect_maze_with_sealed_brick_boundary(seed: int):
    w, h = 2 + seed % 7, 2 + seed % 5
    maze = generate_maze(seed, w, h)
    open_edges = sum(c.edge(d) == "open" for c in maze.cells for d in DIRECTIONS) // 2
    assert open_edges == w * h - 1  # spanning tree
    assert len(maze.path_lengths_from(maze.exit)) == w * h  # connected
    for c in maze.cells:
        for d in DIRECTIONS:
            q = P(c.x, c.y).step(d)
            assert (c.edge(d) == "outer_brick") == (not maze.in_bounds(q))
    assert maze.exit.x in (0, w - 1) or maze.exit.y in (0, h - 1)
    assert len({maze.exit, *maze.spawns}) == 4


def test_generation_is_deterministic_and_seed_sensitive():
    assert generate_maze(7, 15, 15) == generate_maze(7, 15, 15)
    assert generate_maze(7, 15, 15).maze_hash != generate_maze(8, 15, 15).maze_hash


def test_extra_open_edges_create_loops_and_are_recorded():
    maze = generate_maze(3, 8, 8, extra_open_edges=5)
    open_edges = sum(c.edge(d) == "open" for c in maze.cells for d in DIRECTIONS) // 2
    assert open_edges == 64 - 1 + 5
    assert len(maze.generator.extra_open_edges) == 5


def test_inconsistent_hand_authored_walls_rejected():
    maze = grid(3, 3, P(0, 0), [P(1, 1), P(2, 2), P(2, 1)])
    cells = list(maze.cells)
    cells[0] = cells[0].model_copy(update={"east": "interior_wall"})  # reciprocal still open
    with pytest.raises(ValidationError, match="reciprocal"):
        type(maze).model_validate({**maze.model_dump(), "cells": [c.model_dump() for c in cells]})


def test_unreachable_exit_rejected():
    with pytest.raises(ValidationError, match="reachable"):
        build_maze(2, 2, [], P(0, 0), [P(1, 0), P(0, 1), P(1, 1)], HAND_AUTHORED)


def test_distance_formula_matches_rounded_sqrt():
    for dx in range(45):
        for dy in range(45):
            expected = floor(10 * sqrt(dx * dx + dy * dy) + 0.5)
            assert distance_tenths(P(0, 0), P(dx, dy)) == expected


def test_distance_is_euclidean_not_graph_and_zero_when_colocated():
    assert distance_tenths(P(0, 0), P(3, 4)) == 50
    assert distance_tenths(P(0, 0), P(1, 1)) == 14
    assert distance_tenths(P(2, 2), P(2, 2)) == 0


def test_seeded_stream_is_reproducible_per_label():
    draws = [SeededStream(1, "maze").below(1000) for _ in range(3)]
    assert len(set(draws)) == 1
    stream = SeededStream(1, "maze")
    sequence = [stream.below(1000) for _ in range(20)]
    assert len(set(sequence)) > 1
    other = SeededStream(1, "spawns")
    assert [other.below(1000) for _ in range(20)] != sequence
    assert sorted(SeededStream(5, "x").sample(range(10), 10)) == list(range(10))
