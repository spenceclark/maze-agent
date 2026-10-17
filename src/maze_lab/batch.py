"""Paired experiment batches (spec §6.4, §15.1).

An experiment crosses named conditions with environment seeds and replicates.
Every condition sees the same seeds, so the same mazes and spawns: comparisons
are paired by seed. Cells run in an order shuffled by the experiment seed, a
few at a time, and an interrupted batch resumes where it stopped.
"""

import asyncio
import contextlib
import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from maze_lab.agent_contracts import AGENT_IDS, Contract
from maze_lab.config import RunConfig
from maze_lab.coordinator import TERMINAL, Coordinator
from maze_lab.domain.rng import SeededStream
from maze_lab.hashing import content_hash
from maze_lab.persistence.models import RunSummary
from maze_lab.persistence.store import RunStore
from maze_lab.policies.preflight import preflight
from maze_lab.runs import build_policies, create_run


class ExperimentSpec(Contract):
    schema_version: Literal["1.0"] = "1.0"
    name: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    experiment_seed: int = Field(ge=0, lt=2**64)  # orders the cells; never used to build mazes
    base_config: dict[str, Any]  # a RunConfig document; root_seed and condition are set per cell
    seeds: list[int] = Field(min_length=1)
    replicates: int = Field(ge=1)
    conditions: dict[str, dict[str, Any]] = Field(min_length=1)  # name -> overrides, deep-merged
    rotate_agents: bool = False  # rotate agent configs across A/B/C by replicate (mixed-model teams)

    @model_validator(mode="after")
    def _every_cell_is_a_valid_run(self) -> Self:
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be distinct")
        for cell in cells(self):
            config = run_config(self, cell)
            if config.timing.mode == "manual":
                raise ValueError("manual timing needs an operator; use barrier or fixed_deadline")
            preflight(config)
        return self


@dataclass(frozen=True, order=True)
class Cell:
    condition: str
    seed: int
    replicate: int


def load_spec(path: Path) -> ExperimentSpec:
    """Read a spec file. `base_config_file` (relative to the spec) is inlined, with any
    `base_config` in the spec deep-merged over it."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if "base_config_file" in data:
        base = json.loads((path.parent / data.pop("base_config_file")).read_text(encoding="utf-8"))
        data["base_config"] = deep_merge(base, data.get("base_config", {}))
    return ExperimentSpec.model_validate(data)


def deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def cells(spec: ExperimentSpec) -> list[Cell]:
    """Every (condition, seed, replicate), shuffled by the experiment seed."""
    ordered = sorted(
        Cell(c, s, r) for c in spec.conditions for s in spec.seeds for r in range(spec.replicates)
    )
    return SeededStream(spec.experiment_seed, "condition-order").sample(ordered, len(ordered))


def run_config(spec: ExperimentSpec, cell: Cell) -> RunConfig:
    data = deep_merge(spec.base_config, spec.conditions[cell.condition])
    data = {**data, "root_seed": cell.seed, "condition": f"{spec.name}/{cell.condition}"}
    if spec.rotate_agents:
        agents = data["agents"]
        shift = cell.replicate % len(agents)
        data["agents"] = [
            {**agents[(i + shift) % len(agents)], "id": agent_id} for i, agent_id in enumerate(AGENT_IDS)
        ]
    return RunConfig.model_validate(data)


class SpecMismatchError(ValueError):
    """An experiment with this name already exists with a different spec."""


Progress = Callable[[Cell, RunSummary | None, str | None], None]


def is_valid(summary: RunSummary) -> bool:
    """Counts toward results: finished normally, never recovered from a crashed or contested tick."""
    return summary.status == "completed" and not summary.recovered_incomplete_tick


def cell_run_id(spec: ExperimentSpec, cell: Cell, attempt: int) -> str:
    """Deterministic, so two batch processes on one experiment converge on the same run."""
    key = f"{spec.name}|{cell.condition}|{cell.seed}|{cell.replicate}|{attempt}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _claim_run(store: RunStore, spec: ExperimentSpec, cell: Cell, attempt: int) -> str:
    run_id = cell_run_id(spec, cell, attempt)
    if store.summary(run_id) is None:
        with contextlib.suppress(sqlite3.IntegrityError):  # created concurrently by another batch process
            create_run(store, run_config(spec, cell), run_id=run_id)
    return run_id


async def run_batch(
    store: RunStore,
    spec: ExperimentSpec,
    parallel: int = 1,
    progress: Progress | None = None,
    rerun_invalid: bool = False,
) -> None:
    """Run every cell not yet finished. Safe to call again after an interruption.

    With `rerun_invalid`, a cell whose run failed, was cancelled, or recovered from a
    crashed tick gets a fresh attempt; the old run stays in the store for audit. Only
    use it when no other process is driving this experiment.
    """
    # ponytail: one batch process per experiment. A second process never duplicates or corrupts
    # runs (deterministic run ids, fenced coordinators), but runs both touched end up recovered and
    # excluded. Add a lease on the experiment row if batches ever span machines.
    spec_json = spec.model_dump_json()
    existing_hash = store.save_experiment(spec.name, spec_json, content_hash(spec), datetime.now(UTC))
    if existing_hash is not None and existing_hash != content_hash(spec):
        raise SpecMismatchError(f"experiment {spec.name!r} exists with a different spec; use a new name")
    known = store.experiment_runs(spec.name)
    gate = asyncio.Semaphore(parallel)

    async def run_cell(cell: Cell) -> None:
        async with gate:
            try:
                run_id = known.get((cell.condition, cell.seed, cell.replicate))
                summary = store.summary(run_id) if run_id else None
                if run_id is None or (rerun_invalid and summary is not None and not _resumable(summary)):
                    attempt = 0
                    while (existing := store.summary(cell_run_id(spec, cell, attempt))) is not None and (
                        rerun_invalid and not _resumable(existing)
                    ):
                        attempt += 1
                    run_id = _claim_run(store, spec, cell, attempt)
                    store.set_experiment_run(spec.name, cell.condition, cell.seed, cell.replicate, run_id)
                    summary = store.summary(run_id)
                if summary is not None and summary.status not in TERMINAL:
                    policies = build_policies(store.config(run_id))
                    summary = await Coordinator(store, run_id, policies).run()
                if progress:
                    progress(cell, summary, None)
            except Exception as e:  # one failed run must not stop the batch; it is excluded in analysis
                if progress:
                    progress(cell, None, f"{type(e).__name__}: {e}")

    await asyncio.gather(*(run_cell(c) for c in cells(spec)))


def _resumable(summary: RunSummary) -> bool:
    """Valid, or still in progress (resuming it is the normal path)."""
    return is_valid(summary) or (summary.status not in TERMINAL and not summary.recovered_incomplete_tick)
