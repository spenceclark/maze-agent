"""Grid coordinates, compass steps, and the Euclidean distance sensor (spec §4)."""

from math import isqrt

from maze_lab.agent_contracts import Contract, Direction

DIRECTIONS: tuple[Direction, ...] = ("N", "E", "S", "W")

# East increases x, south increases y.
STEP: dict[Direction, tuple[int, int]] = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}


class Position(Contract):
    x: int
    y: int

    def __hash__(self) -> int:  # explicit so type checkers know frozen positions are hashable
        return hash((self.x, self.y))

    def step(self, direction: Direction) -> Position:
        dx, dy = STEP[direction]
        return Position(x=self.x + dx, y=self.y + dy)


def distance_tenths(p: Position, q: Position) -> int:
    """Straight-line distance in tenths of a cell, halves rounded up, exact integer math."""
    dx, dy = p.x - q.x, p.y - q.y
    n = dx * dx + dy * dy
    r = isqrt(100 * n)
    return r + int(400 * n >= (2 * r + 1) ** 2)
