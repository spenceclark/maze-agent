"""Run creation: fixture generation, manifest, initial journal, policy wiring."""

import hashlib
import logging
import platform
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from maze_lab.agent_contracts import AgentId
from maze_lab.config import RunConfig
from maze_lab.domain.generator import GENERATOR_NAME, generate_maze
from maze_lab.domain.rng import PRNG_VERSION, KeyedSampler
from maze_lab.domain.state import initial_state
from maze_lab.hashing import content_hash
from maze_lab.metrics.tracker import MetricsTracker
from maze_lab.persistence.models import (
    EventEnvelope,
    RunCreated,
    RunManifest,
    RunSummary,
    TickCommitted,
    TickSnapshot,
)
from maze_lab.persistence.store import RunStore
from maze_lab.policies.base import AgentPolicy
from maze_lab.policies.baselines import make_baseline
from maze_lab.policies.preflight import preflight
from maze_lab.policies.prompt import PROMPT_MEMORY_NOTES
from maze_lab.policies.pydantic_ai_adapter import ADAPTER_VERSION, PydanticAiPolicy

log = logging.getLogger(__name__)

REDUCER_VERSION = "reducer_v1"
RANDOMNESS = (
    "Each stream is SHA-256('{root_seed}:{label}:{counter}') truncated to 64 bits with rejection "
    "sampling (domain/rng.py). Labels: maze, loops, exit, spawns. Baseline samplers use key "
    "sha256('{root_seed}:baseline:{agent}') and address draws by tick and draw index."
)


def _code_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    except OSError, subprocess.CalledProcessError:
        return None
    return out.stdout.strip() or None


def _lock_hash() -> str | None:
    lock = Path("uv.lock")
    return hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None


def create_run(store: RunStore, config: RunConfig, run_id: str | None = None) -> RunSummary:
    """Validate the config and fixture, then journal `run.created` and tick 0."""
    if config.prompt_version not in PROMPT_MEMORY_NOTES:
        raise ValueError(
            f"prompt_version {config.prompt_version!r} is not runnable; "
            f"use one of {sorted(PROMPT_MEMORY_NOTES)}"
        )
    preflight(config)
    run_id = run_id or uuid.uuid4().hex[:12]
    now = datetime.now(UTC)
    m = config.maze
    maze = generate_maze(config.root_seed, m.width, m.height, m.extra_open_edges, m.landmark_count)
    state = initial_state(maze)
    state_hash = content_hash(state)
    metrics = MetricsTracker(maze, state, config.rules).snapshot()
    if config.horizon_ticks < metrics.oracle_ticks:
        log.warning(
            "horizon_ticks %d is below the %d ticks an omniscient team would need on this maze; "
            "the objective cannot be met",
            config.horizon_ticks,
            metrics.oracle_ticks,
        )
    manifest = RunManifest(
        config=config,
        config_hash=content_hash(config),
        maze_hash=maze.maze_hash,
        initial_state_hash=state_hash,
        dependency_lock_hash=_lock_hash(),
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        code_commit=_code_commit(),
        versions={
            "generator": GENERATOR_NAME,
            "prng": PRNG_VERSION,
            "sampler": KeyedSampler.VERSION,
            "reducer": REDUCER_VERSION,
            "rules": config.rules.version,
            "prompt": config.prompt_version,
            "adapter": ADAPTER_VERSION,
            "metrics": metrics.version,
        },
        randomness=RANDOMNESS,
    )
    summary = RunSummary(
        run_id=run_id,
        status="created",
        committed_tick=0,
        config_hash=manifest.config_hash,
        maze_hash=maze.maze_hash,
        condition=config.condition,
        created_at=now,
        started_at=None,
        ended_at=None,
        termination_reason=None,
        recovered_incomplete_tick=False,
    )
    events = [
        EventEnvelope(
            run_id=run_id,
            sequence=1,
            tick=0,
            type="run.created",
            recorded_at=now,
            payload=RunCreated(manifest_hash=content_hash(manifest), initial_state_hash=state_hash),
        ),
        EventEnvelope(
            run_id=run_id,
            sequence=2,
            tick=0,
            type="tick.committed",
            recorded_at=now,
            payload=TickCommitted(
                state=state, metrics=metrics, state_hash=state_hash, first_sequence=1, last_sequence=2
            ),
        ),
    ]
    snapshot = TickSnapshot(
        run_id=run_id,
        tick=0,
        last_sequence=2,
        maze_hash=maze.maze_hash,
        state=state,
        metrics=metrics,
        state_hash=state_hash,
    )
    store.insert_run(summary, config, maze, manifest, events, snapshot)
    return summary


def baseline_sampler(root_seed: int, agent_id: AgentId) -> KeyedSampler:
    """The policy receives only a derived key, never the root seed (spec §14)."""
    return KeyedSampler(hashlib.sha256(f"{root_seed}:baseline:{agent_id}".encode()).hexdigest())


def build_policies(config: RunConfig) -> dict[AgentId, AgentPolicy]:
    policies: dict[AgentId, AgentPolicy] = {}
    for agent in config.agents:
        if agent.kind == "baseline":
            policies[agent.id] = make_baseline(agent.policy, baseline_sampler(config.root_seed, agent.id))
        else:
            policies[agent.id] = PydanticAiPolicy(
                agent, timeout_s=config.timing.decision_window_ms / 1000, prompt_version=config.prompt_version
            )
    return policies
