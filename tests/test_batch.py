"""Paired batch runner and bootstrap analysis (spec §6.4, §15)."""

import asyncio
import random
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from maze_lab.agent_contracts import AGENT_IDS
from maze_lab.analysis import analyse, bootstrap_mean, render_markdown
from maze_lab.batch import Cell, ExperimentSpec, SpecMismatchError, cells, run_batch, run_config
from maze_lab.persistence.store import RunStore

BASE: dict[str, Any] = {
    "maze": {"width": 5, "height": 5},
    "agents": [{"id": a, "kind": "baseline", "policy": "dfs_bounded_v1"} for a in AGENT_IDS],
    "timing": {"mode": "barrier", "decision_window_ms": 5000},
    "horizon_ticks": 60,
}
RANDOM = {"agents": [{"id": a, "kind": "baseline", "policy": "random_open_v1"} for a in AGENT_IDS]}


def make_spec(**overrides: Any) -> ExperimentSpec:
    data: dict[str, Any] = {
        "name": "dfs_vs_random",
        "experiment_seed": 9,
        "base_config": BASE,
        "seeds": [1, 2],
        "replicates": 2,
        "conditions": {"dfs": {}, "random": RANDOM},
    }
    return ExperimentSpec.model_validate({**data, **overrides})


def test_run_config_applies_condition_seed_and_name():
    spec = make_spec()
    config = run_config(spec, Cell("random", 2, 0))
    assert config.root_seed == 2 and config.condition == "dfs_vs_random/random"
    assert {a.policy for a in config.agents if a.kind == "baseline"} == {"random_open_v1"}
    assert config.maze.width == 5  # base settings survive the deep merge


def test_cells_cover_the_grid_in_a_seeded_shuffled_order():
    spec = make_spec()
    order = cells(spec)
    assert sorted(order) == sorted(Cell(c, s, r) for c in ("dfs", "random") for s in (1, 2) for r in (0, 1))
    assert order == cells(spec)  # reproducible
    assert [cells(make_spec(experiment_seed=s)) for s in range(5)] != [order] * 5  # seed changes the order


def test_rotate_agents_permutes_configs_across_ids():
    mixed = {
        "agents": [
            {"id": "A", "kind": "baseline", "policy": p}
            for p in ("dfs_bounded_v1", "random_open_v1", "wall_follower_v1")
        ]
    }
    spec = make_spec(conditions={"mixed": mixed}, rotate_agents=True)
    by_replicate = [[a.policy for a in run_config(spec, Cell("mixed", 1, r)).agents] for r in range(3)]
    assert by_replicate[0] == ["dfs_bounded_v1", "random_open_v1", "wall_follower_v1"]
    assert by_replicate[1] == ["random_open_v1", "wall_follower_v1", "dfs_bounded_v1"]


@pytest.mark.parametrize(
    "change",
    [{"seeds": [1, 1]}, {"base_config": {**BASE, "timing": {"mode": "manual", "decision_window_ms": 1000}}}],
    ids=["duplicate-seeds", "manual-timing"],
)
def test_invalid_specs_are_rejected(change: dict[str, Any]):
    with pytest.raises(ValidationError):
        make_spec(**change)


def test_batch_runs_resumes_and_reports(tmp_path: Path):
    store = RunStore(tmp_path / "batch.db")
    spec = make_spec()
    asyncio.run(run_batch(store, spec, parallel=3))
    runs = store.experiment_runs(spec.name)
    assert len(runs) == 8

    asyncio.run(run_batch(store, spec, parallel=3))  # resume: nothing new is created
    assert store.experiment_runs(spec.name) == runs

    with pytest.raises(SpecMismatchError):
        asyncio.run(run_batch(store, make_spec(replicates=3)))

    report = analyse(store, spec, baseline="dfs", n_boot=200)
    assert report.resampling_unit == "seed" and report.runs_valid == {"dfs": 4, "random": 4}
    assert report.estimates["dfs"]["success_rate"].mean == 1.0
    assert report.differences["random"]["success_rate"].n == 2  # paired over the two seeds
    assert "Differences from `dfs`" in render_markdown(report)
    store.close()


def test_bootstrap_is_exact_for_constant_values_and_reproducible():
    constant = bootstrap_mean([0.5, 0.5, 0.5], 500, random.Random(1))
    assert (constant.mean, constant.ci_low, constant.ci_high) == (0.5, 0.5, 0.5)
    values = [0.0, 1.0, 1.0, 0.0, 1.0]
    first = bootstrap_mean(values, 500, random.Random(3))
    assert first == bootstrap_mean(values, 500, random.Random(3))
    assert first.ci_low is not None and first.ci_high is not None
    assert first.ci_low <= 0.6 <= first.ci_high
