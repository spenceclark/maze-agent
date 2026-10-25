"""Expert for fine-tuning: depth-first search whose only memory is the agent's own notebook.

It reads one `Observation` (its notebook included) and never the maze, so every decision can be
re-derived from the prompt the model sees. It needs the variants the fine-tune targets:
`coordinates_enabled` in the own-start frame, `used_exits_enabled`, `notebook_ops="append_log"`, and
a perfect maze (`extra_open_edges=0`).

In a perfect maze an open exit missing from `used_exits` always leads to unexplored ground, so the
search is: take an untried exit (N, E, S, W order), otherwise walk back toward the start. Walking
back is local everywhere except at junctions, where `used_exits` no longer tells the way you first
came in from the exits you have tried since. That one fact goes in the notebook, once per junction,
on first arrival:

    junction [3,-2] back W

The line never changes, so the append-only rolling log is enough: nothing has to be rewritten, and
a 15x15 maze has a few dozen junctions at ~25 bytes each, far under the 8192-byte cap, so the log
never drops a line. Landmarks are noted the same way (`landmark piano at [3,-2]`); no decision reads
them, but the prompt asks for them and teammates can use them.
"""

import re
from typing import NamedTuple

from maze_lab.agent_contracts import AppendCheckFirstTurnAction, Direction, Edge, Observation

COMPASS: tuple[Direction, ...] = ("N", "E", "S", "W")
_EDGE_WORDS = {"open": "open", "interior_wall": "wall", "outer_brick": "brick"}
_JUNCTION = re.compile(r"junction \[(-?\d+),(-?\d+)\] back ([NESW])")


class Decision(NamedTuple):
    check: str
    note: str | None
    move: Direction


class MissingMemory(ValueError):
    """A fully explored junction has no `back` line in the notebook, so the way back is unknown."""


def junction_line(x: int, y: int, back: Direction) -> str:
    return f"junction [{x},{y}] back {back}"


def junction_backs(notebook_text: str) -> dict[tuple[int, int], Direction]:
    found: dict[tuple[int, int], Direction] = {}
    for x, y, d in _JUNCTION.findall(notebook_text):
        found[(int(x), int(y))] = d
    return found


def decide(obs: Observation) -> Decision:
    if obs.coordinates is None or obs.used_exits is None:
        raise ValueError("the expert needs rules.coordinates_enabled and rules.used_exits_enabled")
    local = obs.local
    edges: dict[Direction, Edge] = {"N": local.north, "E": local.east, "S": local.south, "W": local.west}
    open_dirs: list[Direction] = [d for d in COMPASS if edges[d] == "open"]
    used = obs.used_exits
    untried: list[Direction] = [d for d in open_dirs if d not in used]
    arrived = obs.last_action.movement.arrived_from
    x, y = obs.coordinates.position
    notebook = obs.notebook.text
    backs = junction_backs(notebook)

    junction = len(open_dirs) >= 3
    kind = "junction" if junction else "corridor" if len(open_dirs) == 2 else "dead end"
    notes: list[str] = []
    # The check states each step of the note decision: the cell's kind, then (at a junction) whether the
    # notebook already has its line. A first model never learned the note when it had to infer both.
    facts = [
        f"at [{x},{y}]",
        ", ".join(f"{d} {_EDGE_WORDS[edges[d]]}" for d in COMPASS),
        f"{len(open_dirs)} open: {kind}",
        f"arrived from {arrived or 'nowhere (start)'}",
        f"used {','.join(used) or 'none'}",
        f"untried {','.join(untried) or 'none'}",
    ]
    if junction and (x, y) in backs:
        facts.append(f"notebook: {junction_line(x, y, backs[(x, y)])}")
    elif junction and arrived is not None and (x, y) != (0, 0):
        notes.append(junction_line(x, y, arrived))
        facts.append(f"notebook: no junction [{x},{y}], noting back {arrived}")
    elif junction:
        facts.append("my start, no way back to note")  # the own-start frame puts the start at [0,0]
    for label in local.landmarks:
        if f"landmark {label} at" not in notebook:
            notes.append(f"landmark {label} at [{x},{y}]")

    move: Direction
    if untried:
        move, why = untried[0], f"go {untried[0]}, untried"
    elif not junction:
        onward: list[Direction] = [d for d in open_dirs if d != arrived]
        move = onward[0] if onward else open_dirs[0]
        why = f"go back {move}" if kind == "dead end" else f"explored, go {move}, the way I did not arrive by"
    elif (x, y) in backs:
        move = backs[(x, y)]
        why = f"junction explored, go back {move}"
    else:
        raise MissingMemory(f"no 'junction [{x},{y}] back' line in the notebook")
    return Decision(check="; ".join([*facts, why]), note="; ".join(notes) or None, move=move)


def reply_json(obs: Observation, decision: Decision) -> str:
    """The ideal reply, keys in the order the check-first schema asks for them."""
    return AppendCheckFirstTurnAction(
        schema_version="1.2",
        tick=obs.decision_tick,
        check=decision.check,
        notebook_append=decision.note,
        move=decision.move,
        radio=None,
    ).model_dump_json()
