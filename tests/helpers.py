"""Small hand-built mazes and action shorthands for engine tests."""

from collections.abc import Iterable

from maze_lab.agent_contracts import AGENT_IDS, AgentId, Direction, Move, NotebookEdit, TurnAction
from maze_lab.config import RulesConfig
from maze_lab.domain.geometry import Position
from maze_lab.domain.maze import GeneratorInfo, MazeDefinition, build_maze
from maze_lab.domain.reducer import Submission, TickResult, resolve
from maze_lab.domain.state import WorldState

HAND_AUTHORED = GeneratorInfo(name="hand", prng="none", root_seed=None, extra_open_edges=[])
RULES = RulesConfig()


def P(x: int, y: int) -> Position:
    return Position(x=x, y=y)


def grid(
    width: int,
    height: int,
    exit: Position,
    spawns: list[Position],
    open_edges: Iterable[tuple[Position, Direction]] | None = None,
) -> MazeDefinition:
    """A maze with the given open edges, or every interior edge open if None."""
    if open_edges is None:
        east: list[tuple[Position, Direction]] = [
            (P(x, y), "E") for y in range(height) for x in range(width - 1)
        ]
        south: list[tuple[Position, Direction]] = [
            (P(x, y), "S") for y in range(height - 1) for x in range(width)
        ]
        open_edges = east + south
    return build_maze(width, height, open_edges, exit, spawns, HAND_AUTHORED)


def act(
    tick: int,
    move: Move = "STAY",
    edit: tuple[int, int, int, str] | None = None,
    radio: str | None = None,
) -> Submission:
    """Submission shorthand. `edit` is (expected_revision, start, end, text)."""
    notebook_edit = None
    if edit is not None:
        rev, start, end, text = edit
        notebook_edit = NotebookEdit(expected_revision=rev, start=start, end=end, text=text)
    action = TurnAction(schema_version="1.0", tick=tick, move=move, notebook_edit=notebook_edit, radio=radio)
    return Submission(action=action, failure=None)


def step(
    maze: MazeDefinition, state: WorldState, rules: RulesConfig = RULES, **subs: Submission
) -> TickResult:
    """Resolve one tick; agents not given explicitly STAY."""
    t = state.tick + 1
    submissions: dict[AgentId, Submission] = {a: subs.get(a, act(t)) for a in AGENT_IDS}
    return resolve(maze, rules, state, submissions)
