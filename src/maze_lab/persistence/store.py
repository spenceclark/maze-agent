"""SQLite (WAL) run store: event journal, atomic tick commits, invocation ledger (spec §9.3).

Exactly one coordinator owns a run at a time. Ownership is a fencing token
(`coordinator_generation`): every commit updates the run row only if the
caller's generation is still current, inside the same transaction as the
events it appends. A stale coordinator therefore cannot write anything.
"""

import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from maze_lab.agent_contracts import AgentId
from maze_lab.config import RunConfig
from maze_lab.domain.maze import MazeDefinition
from maze_lab.persistence.models import (
    CommandReceipt,
    EventEnvelope,
    InvocationRecord,
    NotebookRevision,
    RadioRecord,
    RunManifest,
    RunStatus,
    RunSummary,
    TerminationReason,
    TickCommitted,
    TickSnapshot,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    condition TEXT NOT NULL,
    status TEXT NOT NULL,
    committed_tick INTEGER NOT NULL,
    coordinator_generation INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    termination_reason TEXT,
    recovered_incomplete_tick INTEGER NOT NULL DEFAULT 0,
    config_hash TEXT NOT NULL,
    maze_hash TEXT NOT NULL,
    config_json TEXT NOT NULL,
    maze_json TEXT NOT NULL,
    manifest_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    tick INTEGER NOT NULL,
    type TEXT NOT NULL,
    agent_id TEXT,
    envelope_json TEXT NOT NULL,
    PRIMARY KEY (run_id, sequence)
);
CREATE INDEX IF NOT EXISTS events_by_tick ON events (run_id, tick, type);
CREATE UNIQUE INDEX IF NOT EXISTS one_commit_per_tick ON events (run_id, tick) WHERE type = 'tick.committed';
CREATE TABLE IF NOT EXISTS decisions (
    run_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    tick INTEGER NOT NULL,
    invocation_id TEXT,
    PRIMARY KEY (run_id, agent_id, tick)
);
CREATE TABLE IF NOT EXISTS snapshots (
    run_id TEXT NOT NULL,
    tick INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    PRIMARY KEY (run_id, tick)
);
CREATE TABLE IF NOT EXISTS notebook_revisions (
    run_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    tick INTEGER NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY (run_id, agent_id, revision)
);
CREATE TABLE IF NOT EXISTS radio (
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    sender TEXT NOT NULL,
    sent_tick INTEGER NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY (run_id, sequence)
);
CREATE TABLE IF NOT EXISTS invocations (
    invocation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    tick INTEGER NOT NULL,
    status TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS invocations_by_tick ON invocations (run_id, tick, agent_id);
CREATE TABLE IF NOT EXISTS commands (
    command_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    UNIQUE (run_id, idempotency_key)
);
"""


class LostOwnershipError(RuntimeError):
    """Another coordinator generation now owns this run."""


@dataclass
class CommitBatch:
    """Everything one atomic commit writes. Fields left as None are unchanged."""

    events: list[EventEnvelope]
    committed_tick: int | None = None
    status: RunStatus | None = None
    termination_reason: TerminationReason | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    recovered_incomplete_tick: bool | None = None
    snapshot: TickSnapshot | None = None
    notebook_revisions: list[NotebookRevision] = field(default_factory=list)
    radio: list[RadioRecord] = field(default_factory=list)
    decisions: list[tuple[AgentId, int, str | None]] = field(default_factory=list)


class RunStore:
    def __init__(self, path: str | Path) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self._conn:
            yield self._conn

    # ---- writes -------------------------------------------------------------

    def insert_run(
        self,
        summary: RunSummary,
        config: RunConfig,
        maze: MazeDefinition,
        manifest: RunManifest,
        events: list[EventEnvelope],
        snapshot: TickSnapshot,
    ) -> None:
        with self._tx() as db:
            db.execute(
                "INSERT INTO runs (run_id, condition, status, committed_tick, created_at, config_hash,"
                " maze_hash, config_json, maze_json, manifest_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    summary.run_id,
                    summary.condition,
                    summary.status,
                    summary.committed_tick,
                    summary.created_at.isoformat(),
                    summary.config_hash,
                    summary.maze_hash,
                    config.model_dump_json(),
                    maze.model_dump_json(),
                    manifest.model_dump_json(),
                ),
            )
            self._insert_events(db, events)
            self._insert_snapshot(db, snapshot)

    def acquire(self, run_id: str) -> int:
        """Become the run's coordinator, fencing out any previous generation."""
        with self._tx() as db:
            db.execute(
                "UPDATE runs SET coordinator_generation = coordinator_generation + 1 WHERE run_id = ?",
                (run_id,),
            )
            row = db.execute("SELECT coordinator_generation FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return int(row[0])

    def commit(self, run_id: str, generation: int, batch: CommitBatch) -> None:
        """Apply one batch atomically, or nothing if ownership was lost."""
        updates: dict[str, object] = {
            "committed_tick": batch.committed_tick,
            "status": batch.status,
            "termination_reason": batch.termination_reason,
            "started_at": batch.started_at.isoformat() if batch.started_at else None,
            "ended_at": batch.ended_at.isoformat() if batch.ended_at else None,
            "recovered_incomplete_tick": batch.recovered_incomplete_tick,
        }
        updates = {k: v for k, v in updates.items() if v is not None}
        assignments = ", ".join(f"{k} = ?" for k in updates) or "run_id = run_id"
        with self._tx() as db:
            cursor = db.execute(
                f"UPDATE runs SET {assignments} WHERE run_id = ? AND coordinator_generation = ?",
                (*updates.values(), run_id, generation),
            )
            if cursor.rowcount != 1:
                raise LostOwnershipError(run_id)
            self._insert_events(db, batch.events)
            if batch.snapshot is not None:
                self._insert_snapshot(db, batch.snapshot)
            db.executemany(
                "INSERT INTO notebook_revisions VALUES (?,?,?,?,?)",
                [
                    (r.run_id, r.agent_id, r.revision, r.tick, r.model_dump_json())
                    for r in batch.notebook_revisions
                ],
            )
            db.executemany(
                "INSERT INTO radio VALUES (?,?,?,?,?)",
                [(r.run_id, r.sequence, r.sender, r.sent_tick, r.model_dump_json()) for r in batch.radio],
            )
            db.executemany(
                "INSERT INTO decisions VALUES (?,?,?,?)",
                [(run_id, agent, tick, inv) for agent, tick, inv in batch.decisions],
            )

    def record_invocation(self, record: InvocationRecord) -> None:
        """Upsert a ledger row. Deliberately outside any tick transaction."""
        with self._tx() as db:
            db.execute(
                "INSERT OR REPLACE INTO invocations VALUES (?,?,?,?,?,?)",
                (
                    record.invocation_id,
                    record.run_id,
                    record.agent_id,
                    record.tick,
                    record.status,
                    record.model_dump_json(),
                ),
            )

    def save_command(self, receipt: CommandReceipt, idempotency_key: str, request_hash: str) -> None:
        with self._tx() as db:
            db.execute(
                "INSERT INTO commands VALUES (?,?,?,?,?)",
                (receipt.command_id, receipt.run_id, idempotency_key, request_hash, receipt.model_dump_json()),
            )

    def update_command(self, receipt: CommandReceipt) -> None:
        with self._tx() as db:
            db.execute(
                "UPDATE commands SET receipt_json = ? WHERE command_id = ?",
                (receipt.model_dump_json(), receipt.command_id),
            )

    @staticmethod
    def _insert_events(db: sqlite3.Connection, events: Iterable[EventEnvelope]) -> None:
        db.executemany(
            "INSERT INTO events VALUES (?,?,?,?,?,?)",
            [
                (
                    e.run_id,
                    e.sequence,
                    e.tick,
                    e.type,
                    getattr(e.payload, "agent_id", None),
                    e.model_dump_json(),
                )
                for e in events
            ],
        )

    @staticmethod
    def _insert_snapshot(db: sqlite3.Connection, snapshot: TickSnapshot) -> None:
        db.execute(
            "INSERT OR REPLACE INTO snapshots VALUES (?,?,?)",
            (snapshot.run_id, snapshot.tick, snapshot.model_dump_json()),
        )

    # ---- reads --------------------------------------------------------------

    def _one(self, sql: str, params: tuple[object, ...]) -> tuple[Any, ...] | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def _all(self, sql: str, params: tuple[object, ...]) -> list[tuple[Any, ...]]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def ping(self) -> bool:
        return self._one("SELECT 1", ()) == (1,)

    def summary(self, run_id: str) -> RunSummary | None:
        row = self._one(f"SELECT {_SUMMARY_COLUMNS} FROM runs WHERE run_id = ?", (run_id,))
        return _summary(row) if row else None

    def summaries(self, status: RunStatus | None = None, condition: str | None = None) -> list[RunSummary]:
        rows = self._all(
            f"SELECT {_SUMMARY_COLUMNS} FROM runs"
            " WHERE (? IS NULL OR status = ?) AND (? IS NULL OR condition = ?)"
            " ORDER BY created_at, run_id",
            (status, status, condition, condition),
        )
        return [_summary(r) for r in rows]

    def config(self, run_id: str) -> RunConfig:
        return RunConfig.model_validate_json(self._text("config_json", run_id))

    def maze(self, run_id: str) -> MazeDefinition:
        return MazeDefinition.model_validate_json(self._text("maze_json", run_id))

    def manifest(self, run_id: str) -> RunManifest:
        return RunManifest.model_validate_json(self._text("manifest_json", run_id))

    def _text(self, column: str, run_id: str) -> str:
        row = self._one(f"SELECT {column} FROM runs WHERE run_id = ?", (run_id,))
        if row is None:
            raise KeyError(run_id)
        return str(row[0])

    def last_sequence(self, run_id: str) -> int:
        row = self._one("SELECT MAX(sequence) FROM events WHERE run_id = ?", (run_id,))
        return int(row[0]) if row and row[0] is not None else 0

    def events(
        self,
        run_id: str,
        after_sequence: int = 0,
        to_tick: int | None = None,
        types: list[str] | None = None,
        agent_id: AgentId | None = None,
        limit: int | None = None,
    ) -> list[EventEnvelope]:
        sql = "SELECT envelope_json FROM events WHERE run_id = ? AND sequence > ?"
        params: list[object] = [run_id, after_sequence]
        if to_tick is not None:
            sql += " AND tick <= ?"
            params.append(to_tick)
        if types:
            sql += f" AND type IN ({','.join('?' * len(types))})"
            params.extend(types)
        if agent_id is not None:
            sql += " AND agent_id = ?"
            params.append(agent_id)
        sql += " ORDER BY sequence"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [EventEnvelope.model_validate_json(str(r[0])) for r in self._all(sql, tuple(params))]

    def tick_commit(self, run_id: str, tick: int) -> TickCommitted | None:
        row = self._one(
            "SELECT envelope_json FROM events WHERE run_id = ? AND tick = ? AND type = 'tick.committed'",
            (run_id, tick),
        )
        if row is None:
            return None
        payload = EventEnvelope.model_validate_json(str(row[0])).payload
        assert isinstance(payload, TickCommitted)
        return payload

    def snapshots(self, run_id: str) -> list[TickSnapshot]:
        rows = self._all("SELECT snapshot_json FROM snapshots WHERE run_id = ? ORDER BY tick", (run_id,))
        return [TickSnapshot.model_validate_json(str(r[0])) for r in rows]

    def notebook_revisions(self, run_id: str, agent_id: AgentId | None = None) -> list[NotebookRevision]:
        rows = self._all(
            "SELECT record_json FROM notebook_revisions WHERE run_id = ? AND (? IS NULL OR agent_id = ?)"
            " ORDER BY agent_id, revision",
            (run_id, agent_id, agent_id),
        )
        return [NotebookRevision.model_validate_json(str(r[0])) for r in rows]

    def radio(self, run_id: str) -> list[RadioRecord]:
        rows = self._all("SELECT record_json FROM radio WHERE run_id = ? ORDER BY sequence", (run_id,))
        return [RadioRecord.model_validate_json(str(r[0])) for r in rows]

    def command_by_key(self, run_id: str, idempotency_key: str) -> tuple[str, CommandReceipt] | None:
        """(request hash, receipt) for an idempotency key already used on this run."""
        row = self._one(
            "SELECT request_hash, receipt_json FROM commands WHERE run_id = ? AND idempotency_key = ?",
            (run_id, idempotency_key),
        )
        return (row[0], CommandReceipt.model_validate_json(row[1])) if row else None

    def commands(self, run_id: str) -> list[CommandReceipt]:
        rows = self._all("SELECT receipt_json FROM commands WHERE run_id = ? ORDER BY rowid", (run_id,))
        return [CommandReceipt.model_validate_json(r[0]) for r in rows]

    def invocations(
        self, run_id: str, tick: int | None = None, agent_id: AgentId | None = None
    ) -> list[InvocationRecord]:
        rows = self._all(
            "SELECT record_json FROM invocations WHERE run_id = ? AND (? IS NULL OR tick = ?)"
            " AND (? IS NULL OR agent_id = ?) ORDER BY tick, agent_id",
            (run_id, tick, tick, agent_id, agent_id),
        )
        return [InvocationRecord.model_validate_json(str(r[0])) for r in rows]


_SUMMARY_COLUMNS = (
    "run_id, status, committed_tick, config_hash, maze_hash, condition, created_at, started_at,"
    " ended_at, termination_reason, recovered_incomplete_tick"
)


def _summary(row: tuple[object, ...]) -> RunSummary:
    keys = [k.strip() for k in _SUMMARY_COLUMNS.split(",")]
    data = dict(zip(keys, row, strict=True))
    data["recovered_incomplete_tick"] = bool(data["recovered_incomplete_tick"])
    for k in ("created_at", "started_at", "ended_at"):
        if data[k] is not None:
            data[k] = datetime.fromisoformat(str(data[k]))
    return RunSummary.model_validate(data)
