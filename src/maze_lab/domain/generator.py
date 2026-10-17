"""Seeded maze generation, `dfs_v1` (spec §3, §16).

Algorithm, fixed for this version:
1. `maze` stream: start cell uniform; iterative randomized DFS, choosing
   uniformly among unvisited neighbours listed in N, E, S, W order.
2. `loops` stream: sample `extra_open_edges` from the closed interior edges,
   listed row-major with E before S for each cell.
3. `exit` stream: uniform perimeter cell, row-major order.
4. `spawns` stream: three distinct non-exit cells, row-major order, assigned A, B, C.
5. `landmarks` stream: distinct cells (any cell, row-major order); `landmark-labels` stream:
   distinct labels from the fixed vocabulary. Separate streams, so turning landmarks on
   changes nothing else about the maze.
"""

from maze_lab.agent_contracts import OPPOSITE, Direction
from maze_lab.config import LANDMARK_LABELS
from maze_lab.domain.geometry import DIRECTIONS, Position
from maze_lab.domain.maze import GeneratorInfo, Landmark, MazeDefinition, build_maze
from maze_lab.domain.rng import PRNG_VERSION, SeededStream

GENERATOR_NAME = "dfs_v1"
FORWARD: tuple[Direction, ...] = ("E", "S")  # lists each interior edge once


def generate_maze(
    root_seed: int, width: int, height: int, extra_open_edges: int = 0, landmark_count: int = 0
) -> MazeDefinition:
    cells = [Position(x=x, y=y) for y in range(height) for x in range(width)]

    def in_bounds(p: Position) -> bool:
        return 0 <= p.x < width and 0 <= p.y < height

    rng = SeededStream(root_seed, "maze")
    start = rng.choice(cells)
    visited = {start}
    stack = [start]
    tree: set[tuple[Position, Direction]] = set()
    while stack:
        here = stack[-1]
        options: list[Direction] = [
            d for d in DIRECTIONS if in_bounds(here.step(d)) and here.step(d) not in visited
        ]
        if not options:
            stack.pop()
            continue
        d = rng.choice(options)
        nxt = here.step(d)
        tree.add((here, d))
        visited.add(nxt)
        stack.append(nxt)

    opened = tree | {(p.step(d), OPPOSITE[d]) for p, d in tree}
    closed: list[tuple[Position, Direction]] = [
        (p, d) for p in cells for d in FORWARD if in_bounds(p.step(d)) and (p, d) not in opened
    ]
    if extra_open_edges > len(closed):
        raise ValueError(f"only {len(closed)} closed interior edges available")
    loops = SeededStream(root_seed, "loops").sample(closed, extra_open_edges)

    perimeter = [p for p in cells if p.x in (0, width - 1) or p.y in (0, height - 1)]
    exit = SeededStream(root_seed, "exit").choice(perimeter)
    spawns = SeededStream(root_seed, "spawns").sample([p for p in cells if p != exit], 3)

    info = GeneratorInfo(
        name=GENERATOR_NAME,
        prng=PRNG_VERSION,
        root_seed=root_seed,
        extra_open_edges=sorted(loops, key=_edge_key),
    )
    spots = SeededStream(root_seed, "landmarks").sample(cells, landmark_count)
    labels = SeededStream(root_seed, "landmark-labels").sample(LANDMARK_LABELS, landmark_count)
    landmarks = [Landmark(position=p, label=label) for p, label in zip(spots, labels, strict=True)]
    return build_maze(width, height, [*tree, *loops], exit, spawns, info, landmarks)


def _edge_key(edge: tuple[Position, Direction]) -> tuple[int, int, str]:
    p, d = edge
    return (p.y, p.x, d)
