"""Experiment analysis: per-run outcomes and paired bootstrap comparisons (spec §15.2).

The resampling unit is the environment seed, so three agents and several
replicates on one maze are not treated as independent mazes. With a single
seed there is nothing to resample at that level, so replicates become the
unit and the report says so. Success rate is always reported next to
success-only measures such as path efficiency.
"""

import random
from collections import defaultdict
from collections.abc import Callable
from statistics import fmean

from pydantic import BaseModel

from maze_lab.agent_contracts import Contract
from maze_lab.batch import ExperimentSpec
from maze_lab.persistence.store import RunStore
from maze_lab.transcript import build_transcripts

CI_LEVEL = 0.95


class RunOutcome(Contract):
    run_id: str
    condition: str
    seed: int
    replicate: int
    status: str
    valid: bool  # completed and not recovered from a crash; invalid runs are excluded and counted
    success: bool  # team objective met within the horizon
    agents_exited: int
    completion_tick: int | None  # censored (None) when the objective was not met
    oracle_ticks: int
    mean_path_efficiency: float | None  # over agents that reached the exit
    coverage: float
    mean_revisit_fraction: float | None
    blocked_moves: int
    forced_stays: int
    cost_usd: float | None
    input_tokens: int | None
    output_tokens: int | None
    # Stall measures (spec §15.2 is silent on these; they track the dominant failure seen in pilots)
    mean_progress: float  # per agent: fraction of its spawn-to-exit path distance closed at its best
    ticks_since_new_cell: float | None  # agents that never exited: ticks since they last entered a new cell
    stays_before_exit: int  # deliberate STAYs taken before each agent's first exit (whole run if none)


def _agent_trajectory_measures(store: RunStore, run_id: str) -> tuple[float, float | None, int]:
    maze = store.maze(run_id)
    dist = maze.path_lengths_from(maze.exit)
    progress: list[float] = []
    stalled: list[float] = []
    stays = 0
    for entries in build_transcripts(store, run_id).values():
        if not entries:
            continue
        start = dist[entries[0].spectator.position_before]
        best = min([start] + [dist[e.spectator.position_after] for e in entries])
        progress.append(1.0 if start == 0 else (start - best) / start)
        seen = {entries[0].spectator.position_before}
        last_new = 0
        for e in entries:
            if e.spectator.position_after not in seen:
                seen.add(e.spectator.position_after)
                last_new = e.tick
            exited_before = e.spectator.first_exit_tick is not None and e.spectator.first_exit_tick < e.tick
            if e.outcome.movement.outcome == "stayed" and not exited_before:
                stays += 1
        if entries[-1].spectator.first_exit_tick is None:
            stalled.append(float(entries[-1].tick - last_new))
    return fmean(progress), (fmean(stalled) if stalled else None), stays


def _mean_or_none(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return fmean(present) if present else None


def collect_outcomes(store: RunStore, spec: ExperimentSpec) -> list[RunOutcome]:
    outcomes = []
    for (condition, seed, replicate), run_id in sorted(store.experiment_runs(spec.name).items()):
        summary = store.summary(run_id)
        if summary is None:
            continue
        commit = store.tick_commit(run_id, summary.committed_tick)
        if commit is None:
            continue
        m = commit.metrics
        agents = list(m.agents.values())
        costs = [a.estimated_cost_usd for a in agents]
        progress, stalled, stays = _agent_trajectory_measures(store, run_id)
        outcomes.append(
            RunOutcome(
                run_id=run_id,
                condition=condition,
                seed=seed,
                replicate=replicate,
                status=summary.status,
                valid=summary.status == "completed" and not summary.recovered_incomplete_tick,
                success=m.objective_met_tick is not None,
                agents_exited=sum(a.first_exit_tick is not None for a in agents),
                completion_tick=m.objective_met_tick,
                oracle_ticks=m.oracle_ticks,
                mean_path_efficiency=_mean_or_none([a.path_efficiency for a in agents]),
                coverage=m.coverage,
                mean_revisit_fraction=_mean_or_none([a.revisit_fraction for a in agents]),
                blocked_moves=sum(a.blocked for a in agents),
                forced_stays=sum(a.forced_stays for a in agents),
                cost_usd=sum(c for c in costs if c is not None)
                if any(c is not None for c in costs)
                else None,
                input_tokens=sum(a.input_tokens or 0 for a in agents),
                output_tokens=sum(a.output_tokens or 0 for a in agents),
                mean_progress=progress,
                ticks_since_new_cell=stalled,
                stays_before_exit=stays,
            )
        )
    return outcomes


MetricFn = Callable[[RunOutcome], float | None]

METRICS: dict[str, MetricFn] = {
    "success_rate": lambda o: float(o.success),
    "agents_exited": lambda o: float(o.agents_exited),
    "completion_tick (successes only)": lambda o: (
        None if o.completion_tick is None else float(o.completion_tick)
    ),
    "path_efficiency (exited agents)": lambda o: o.mean_path_efficiency,
    "progress_to_exit": lambda o: o.mean_progress,
    "ticks_since_new_cell (non-exited)": lambda o: o.ticks_since_new_cell,
    "stays_before_exit": lambda o: float(o.stays_before_exit),
    "coverage": lambda o: o.coverage,
    "revisit_fraction": lambda o: o.mean_revisit_fraction,
    "blocked_moves": lambda o: float(o.blocked_moves),
    "forced_stays": lambda o: float(o.forced_stays),
    "cost_usd": lambda o: o.cost_usd,
}


class Estimate(BaseModel):
    n: int  # resampling units contributing a value
    mean: float | None
    ci_low: float | None
    ci_high: float | None


def _percentile_ci(samples: list[float]) -> tuple[float, float]:
    ordered = sorted(samples)
    alpha = (1 - CI_LEVEL) / 2
    lo = ordered[int(alpha * (len(ordered) - 1))]
    hi = ordered[int((1 - alpha) * (len(ordered) - 1))]
    return lo, hi


def bootstrap_mean(units: list[float], n_boot: int, rng: random.Random) -> Estimate:
    """Mean of per-unit values with a percentile bootstrap CI over units."""
    if not units:
        return Estimate(n=0, mean=None, ci_low=None, ci_high=None)
    means = [fmean(rng.choices(units, k=len(units))) for _ in range(n_boot)]
    lo, hi = _percentile_ci(means)
    return Estimate(n=len(units), mean=fmean(units), ci_low=lo, ci_high=hi)


def bootstrap_difference(a: list[float], b: list[float], n_boot: int, rng: random.Random) -> Estimate:
    """Unpaired mean(a) - mean(b), resampling each side independently (single-seed fallback)."""
    if not a or not b:
        return Estimate(n=0, mean=None, ci_low=None, ci_high=None)
    diffs = [fmean(rng.choices(a, k=len(a))) - fmean(rng.choices(b, k=len(b))) for _ in range(n_boot)]
    lo, hi = _percentile_ci(diffs)
    return Estimate(n=min(len(a), len(b)), mean=fmean(a) - fmean(b), ci_low=lo, ci_high=hi)


class ExperimentReport(BaseModel):
    experiment: str
    baseline: str
    resampling_unit: str  # "seed" or "replicate (single seed)"
    runs_planned: int
    runs_valid: dict[str, int]
    runs_excluded: dict[str, list[str]]  # condition -> excluded run ids with status
    estimates: dict[str, dict[str, Estimate]]  # condition -> metric -> estimate
    differences: dict[str, dict[str, Estimate]]  # condition -> metric -> (condition - baseline)


def _per_seed_means(outcomes: list[RunOutcome], metric: MetricFn) -> dict[int, float]:
    by_seed: dict[int, list[float]] = defaultdict(list)
    for o in outcomes:
        if (value := metric(o)) is not None:
            by_seed[o.seed].append(value)
    return {seed: fmean(values) for seed, values in by_seed.items()}


def analyse(
    store: RunStore, spec: ExperimentSpec, baseline: str | None = None, n_boot: int = 2000, seed: int = 0
) -> ExperimentReport:
    """Bootstrap is seeded for reproducible reports; it never touches environment randomness."""
    baseline = baseline or next(iter(spec.conditions))
    if baseline not in spec.conditions:
        raise ValueError(f"unknown baseline condition {baseline!r}")
    rng = random.Random(seed)
    outcomes = collect_outcomes(store, spec)
    valid = [o for o in outcomes if o.valid]
    by_condition = {c: [o for o in valid if o.condition == c] for c in spec.conditions}
    per_seed = len(spec.seeds) >= 2

    estimates: dict[str, dict[str, Estimate]] = {}
    differences: dict[str, dict[str, Estimate]] = {}
    for condition, runs in by_condition.items():
        estimates[condition] = {}
        for name, metric in METRICS.items():
            units = (
                list(_per_seed_means(runs, metric).values())
                if per_seed
                else [v for o in runs if (v := metric(o)) is not None]
            )
            estimates[condition][name] = bootstrap_mean(units, n_boot, rng)
        if condition == baseline:
            continue
        differences[condition] = {}
        for name, metric in METRICS.items():
            if per_seed:
                mine, base = _per_seed_means(runs, metric), _per_seed_means(by_condition[baseline], metric)
                paired = [mine[s] - base[s] for s in mine.keys() & base.keys()]
                differences[condition][name] = bootstrap_mean(paired, n_boot, rng)
            else:
                mine_v = [v for o in runs if (v := metric(o)) is not None]
                base_v = [v for o in by_condition[baseline] if (v := metric(o)) is not None]
                differences[condition][name] = bootstrap_difference(mine_v, base_v, n_boot, rng)

    excluded: dict[str, list[str]] = defaultdict(list)
    for o in outcomes:
        if not o.valid:
            excluded[o.condition].append(f"{o.run_id} ({o.status})")
    return ExperimentReport(
        experiment=spec.name,
        baseline=baseline,
        resampling_unit="seed" if per_seed else "replicate (single seed)",
        runs_planned=len(spec.conditions) * len(spec.seeds) * spec.replicates,
        runs_valid={c: len(r) for c, r in by_condition.items()},
        runs_excluded=dict(excluded),
        estimates=estimates,
        differences=differences,
    )


def _fmt(e: Estimate) -> str:
    if e.mean is None or e.ci_low is None or e.ci_high is None:
        return "n/a"
    return f"{e.mean:.3g} [{e.ci_low:.3g}, {e.ci_high:.3g}] (n={e.n})"


def render_markdown(report: ExperimentReport) -> str:
    conditions = list(report.estimates)
    lines = [
        f"# Experiment `{report.experiment}`",
        "",
        f"Runs planned: {report.runs_planned}. Valid runs: "
        + ", ".join(f"{c} {n}" for c, n in report.runs_valid.items())
        + f". Resampling unit: {report.resampling_unit}. Intervals are {CI_LEVEL:.0%} percentile bootstrap.",
        "",
        "## Estimates: mean [CI] (n)",
        "",
        "| Metric | " + " | ".join(conditions) + " |",
        "| --- |" + " --- |" * len(conditions),
    ]
    for metric in METRICS:
        lines.append(
            f"| {metric} | " + " | ".join(_fmt(report.estimates[c][metric]) for c in conditions) + " |"
        )
    if report.differences:
        others = list(report.differences)
        lines += [
            "",
            f"## Differences from `{report.baseline}`: mean [CI] (n)",
            "",
            "| Metric | " + " | ".join(f"{c} - {report.baseline}" for c in others) + " |",
            "| --- |" + " --- |" * len(others),
        ]
        for metric in METRICS:
            lines.append(
                f"| {metric} | " + " | ".join(_fmt(report.differences[c][metric]) for c in others) + " |"
            )
    if report.runs_excluded:
        lines += ["", "## Excluded runs", ""]
        lines += [f"- {c}: {', '.join(ids)}" for c, ids in report.runs_excluded.items()]
    return "\n".join(lines) + "\n"
