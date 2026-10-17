"""Ground-truth maze definition (spec §4.1, §8). Spectator/scorer only."""

from collections import deque
from collections.abc import Iterable
from typing import Literal, Self

from pydantic import Field, model_validator

from maze_lab.agent_contracts import OPPOSITE, Contract, Direction, Edge
from maze_lab.domain.geometry import DIRECTIONS, Position
from maze_lab.hashing import content_hash


class CellDef(Contract):
    x: int
    y: int
    north: Edge
    east: Edge
    south: Edge
    west: Edge

    def edge(self, direction: Direction) -> Edge:
        edges: dict[Direction, Edge] = {"N": self.north, "E": self.east, "S": self.south, "W": self.west}
        return edges[direction]


class GeneratorInfo(Contract):
    name: str
    prng: str
    root_seed: int | None
    extra_open_edges: list[tuple[Position, Direction]]


class MazeDefinition(Contract):
    version: Literal["1.0"] = "1.0"
    width: int = Field(ge=2)
    height: int = Field(ge=2)
    cells: list[CellDef]
    exit: Position
    spawns: list[Position] = Field(min_length=3, max_length=3)  # A, B, C
    generator: GeneratorInfo
    maze_hash: str

    def in_bounds(self, p: Position) -> bool:
        return 0 <= p.x < self.width and 0 <= p.y < self.height

    def cell(self, p: Position) -> CellDef:
        return self.cells[p.y * self.width + p.x]

    def edge(self, p: Position, direction: Direction) -> Edge:
        return self.cell(p).edge(direction)

    def open_neighbors(self, p: Position) -> list[Position]:
        return [p.step(d) for d in DIRECTIONS if self.edge(p, d) == "open"]

    def path_lengths_from(self, start: Position) -> dict[Position, int]:
        """BFS shortest-path lengths over open edges (oracle/metrics only)."""
        dist = {start: 0}
        queue = deque([start])
        while queue:
            p = queue.popleft()
            for q in self.open_neighbors(p):
                if q not in dist:
                    dist[q] = dist[p] + 1
                    queue.append(q)
        return dist

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        w, h = self.width, self.height
        if [(c.x, c.y) for c in self.cells] != [(x, y) for y in range(h) for x in range(w)]:
            raise ValueError("cells must be listed row-major and cover the grid")
        for c in self.cells:
            p = Position(x=c.x, y=c.y)
            for d in DIRECTIONS:
                q, e = p.step(d), c.edge(d)
                if not self.in_bounds(q):
                    if e != "outer_brick":
                        raise ValueError(f"boundary edge {p}{d} must be outer_brick")
                elif e == "outer_brick":
                    raise ValueError(f"interior edge {p}{d} must not be outer_brick")
                elif self.cell(q).edge(OPPOSITE[d]) != e:
                    raise ValueError(f"edge {p}{d} disagrees with its reciprocal")
        points = [self.exit, *self.spawns]
        if not all(self.in_bounds(p) for p in points):
            raise ValueError("exit and spawns must be in bounds")
        if len(set(points)) != len(points):
            raise ValueError("spawns must be distinct non-exit cells")
        reachable = self.path_lengths_from(self.exit)
        if not all(s in reachable for s in self.spawns):
            raise ValueError("exit must be reachable from every spawn")
        if self.maze_hash != _hash_body(self):
            raise ValueError("maze_hash does not match content")
        return self


def _hash_body(maze: MazeDefinition) -> str:
    return content_hash(maze.model_dump(mode="json", exclude={"maze_hash"}))


def build_maze(
    width: int,
    height: int,
    open_edges: Iterable[tuple[Position, Direction]],
    exit: Position,
    spawns: list[Position],
    generator: GeneratorInfo,
) -> MazeDefinition:
    """Assemble a validated maze from the set of open interior edges."""
    opened: set[tuple[Position, Direction]] = set()
    for p, d in open_edges:
        opened |= {(p, d), (p.step(d), OPPOSITE[d])}

    def edge(p: Position, d: Direction) -> Edge:
        q = p.step(d)
        if not (0 <= q.x < width and 0 <= q.y < height):
            return "outer_brick"
        return "open" if (p, d) in opened else "interior_wall"

    cells = []
    for y in range(height):
        for x in range(width):
            p = Position(x=x, y=y)
            cells.append(
                CellDef(
                    x=x, y=y, north=edge(p, "N"), east=edge(p, "E"), south=edge(p, "S"), west=edge(p, "W")
                )
            )
    body = {
        "version": "1.0",
        "width": width,
        "height": height,
        "cells": cells,
        "exit": exit,
        "spawns": spawns,
        "generator": generator,
    }
    draft = MazeDefinition.model_construct(**body, maze_hash="")
    return MazeDefinition(**body, maze_hash=_hash_body(draft))
