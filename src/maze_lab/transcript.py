"""Per-agent, turn-by-turn transcripts for post-run analysis (one JSONL line per decision).

Each line joins what one agent saw, what it answered, what happened, and what
it remembered afterwards. Ground truth the agent never saw is kept apart under
`spectator` so an analyst (human or model) can tell the two apart.
"""

from pathlib import Path
from typing import Literal

from maze_lab.agent_contracts import (
    AGENT_IDS,
    ActionReceipt,
    AgentId,
    AnyTurnAction,
    Contract,
    Notebook,
    Observation,
)
from maze_lab.domain.events import DecisionResolved, RadioSent
from maze_lab.domain.geometry import Position, distance_tenths
from maze_lab.persistence.models import InvocationRecord
from maze_lab.persistence.store import RunStore
from maze_lab.policies.base import Usage
from maze_lab.replay import iter_committed_ticks


class SpectatorFacts(Contract):
    """Ground truth for this turn. Never part of the agent's input."""

    position_before: Position
    position_after: Position
    exit_position: Position
    exit_distance_tenths_after: int
    first_exit_tick: int | None
    colocated_after: list[AgentId]


class TranscriptEntry(Contract):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    agent_id: AgentId
    tick: int  # decision tick: the observation shows state tick - 1, the outcome is state tick
    observation: Observation | None  # exactly what the agent was shown; None if not recorded
    response_text: str | None  # raw model output, before parsing
    action: AnyTurnAction | None  # parsed action; None when the decision failed
    failure: str | None
    error_detail: str | None
    outcome: ActionReceipt  # what the engine did with the action
    radio_sent: str | None  # accepted transmission, heard by peers next turn
    notebook_after: Notebook
    usage: Usage | None
    latency_ms: float | None
    spectator: SpectatorFacts


def build_transcripts(store: RunStore, run_id: str) -> dict[AgentId, list[TranscriptEntry]]:
    maze = store.maze(run_id)
    invocations: dict[tuple[int, AgentId], InvocationRecord] = {}
    for record in store.invocations(run_id):  # the latest coordinator generation wins
        key = (record.tick, record.agent_id)
        if key not in invocations or record.coordinator_generation > invocations[key].coordinator_generation:
            invocations[key] = record

    transcripts: dict[AgentId, list[TranscriptEntry]] = {a: [] for a in AGENT_IDS}
    for tick in iter_committed_ticks(store, run_id):
        after = tick.commit.state
        sent = {e.sender: e.text for e in tick.events if isinstance(e, RadioSent)}
        for decision in (e for e in tick.events if isinstance(e, DecisionResolved)):
            agent = decision.agent_id
            record = invocations.get((tick.tick, agent))
            attempt = record.attempt if record else None
            now = after.agent(agent)
            group = next((g for g in after.meetings if agent in g), [])
            transcripts[agent].append(
                TranscriptEntry(
                    run_id=run_id,
                    agent_id=agent,
                    tick=tick.tick,
                    observation=record.observation if record else None,
                    response_text=attempt.response_text if attempt else None,
                    action=decision.action,
                    failure=decision.receipt.movement.cause
                    if decision.receipt.movement.outcome == "forced_stay"
                    else None,
                    error_detail=attempt.error_detail if attempt else None,
                    outcome=decision.receipt,
                    radio_sent=sent.get(agent),
                    notebook_after=now.notebook,
                    usage=attempt.usage if attempt else None,
                    latency_ms=record.duration_ms if record else None,
                    spectator=SpectatorFacts(
                        position_before=tick.prev.agent(agent).position,
                        position_after=now.position,
                        exit_position=maze.exit,
                        exit_distance_tenths_after=distance_tenths(now.position, maze.exit),
                        first_exit_tick=now.first_exit_tick,
                        colocated_after=[a for a in group if a != agent],
                    ),
                )
            )
    return transcripts


def transcript_files(store: RunStore, run_id: str) -> dict[str, bytes]:
    """`{agent}.jsonl` file contents, one entry per line in tick order."""
    return {
        f"{agent}.jsonl": "".join(e.model_dump_json() + "\n" for e in entries).encode()
        for agent, entries in build_transcripts(store, run_id).items()
    }


def write_transcripts(store: RunStore, run_id: str, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, data in transcript_files(store, run_id).items():
        path = out_dir / name
        path.write_bytes(data)
        paths.append(path)
    return paths
