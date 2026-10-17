"""Exploratory behaviour markers, read from transcripts (not primary metrics; spec §15.2).

Heuristic text and trajectory signals for the habits that separated a successful
Sonnet run from Haiku's stalls: keeping coordinates, estimating the exit's
position, sharing routes that start from a landmark, and accepting moves that
raise the straight-line reading. Regex markers can miss or over-count; read
transcripts before drawing conclusions from them.
"""

import re
from collections import defaultdict
from statistics import fmean

from pydantic import BaseModel

from maze_lab.domain.geometry import distance_tenths
from maze_lab.persistence.store import RunStore
from maze_lab.transcript import build_transcripts

_COORD = re.compile(r"\(\s*-?\d+\s*,\s*-?\d+\s*\)")
_EXIT_ESTIMATE = re.compile(r"exit[^.\n]{0,60}\(\s*-?\d+\s*,\s*-?\d+\s*\)", re.IGNORECASE)
_MOVE_LIST = re.compile(r"\b[NESW]\b(?:\s*,\s*\b[NESW]\b){2,}|\b[NESW]\d\b(?:\s*,\s*\b[NESW]\d\b)+")


class AgentMarkers(BaseModel):
    coordinates: bool  # notebook ever records (x, y) pairs
    exit_estimate: bool  # notebook ever places the exit at coordinates
    landmark_route_messages: int  # radio messages naming a landmark and a move sequence
    away_move_share: float | None  # successful moves that raised the straight-line exit reading
    exited: bool


def _names_landmark(text: str, labels: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(label)}\b", text, re.IGNORECASE) for label in labels)


def run_markers(store: RunStore, run_id: str) -> list[AgentMarkers]:
    maze = store.maze(run_id)
    labels = [lm.label for lm in maze.landmarks]
    markers = []
    for entries in build_transcripts(store, run_id).values():
        notes = " ".join(e.notebook_after.text for e in entries)
        routes = 0
        away = moves = 0
        for e in entries:
            if e.radio_sent and _MOVE_LIST.search(e.radio_sent) and _names_landmark(e.radio_sent, labels):
                routes += 1
            if e.outcome.movement.outcome == "moved":
                moves += 1
                before = distance_tenths(e.spectator.position_before, maze.exit)
                after = distance_tenths(e.spectator.position_after, maze.exit)
                away += after > before
        markers.append(
            AgentMarkers(
                coordinates=bool(_COORD.search(notes)),
                exit_estimate=bool(_EXIT_ESTIMATE.search(notes)),
                landmark_route_messages=routes,
                away_move_share=away / moves if moves else None,
                exited=entries[-1].spectator.first_exit_tick is not None,
            )
        )
    return markers


def summarise(store: RunStore, experiment: str) -> dict[str, dict[str, float]]:
    """Per condition: share of agents with each habit, and means of the counts."""
    by_condition: dict[str, list[AgentMarkers]] = defaultdict(list)
    for (condition, _seed, _rep), run_id in store.experiment_runs(experiment).items():
        by_condition[condition] += run_markers(store, run_id)
    summary = {}
    for condition, agents in sorted(by_condition.items()):
        shares = [a.away_move_share for a in agents if a.away_move_share is not None]
        summary[condition] = {
            "agents": len(agents),
            "keep_coordinates": fmean(a.coordinates for a in agents),
            "estimate_exit_position": fmean(a.exit_estimate for a in agents),
            "landmark_route_messages_per_agent": fmean(a.landmark_route_messages for a in agents),
            "away_move_share": fmean(shares) if shares else float("nan"),
            "exited": fmean(a.exited for a in agents),
        }
    return summary
