"""Per-agent transcripts line up with the journal, turn by turn."""

import asyncio
import zipfile
from itertools import pairwise
from pathlib import Path

from maze_lab.agent_contracts import AGENT_IDS
from maze_lab.config import RunConfig
from maze_lab.coordinator import Coordinator
from maze_lab.export import export_run, verify_export
from maze_lab.persistence.store import RunStore
from maze_lab.runs import build_policies, create_run
from maze_lab.transcript import TranscriptEntry, write_transcripts


def test_transcripts_follow_each_agent_turn_by_turn(tmp_path: Path):
    store = RunStore(tmp_path / "t.db")
    config = RunConfig.model_validate(
        {
            "root_seed": 3,
            "condition": "transcript",
            "maze": {"width": 6, "height": 6},
            "agents": [{"id": a, "kind": "baseline", "policy": "dfs_bounded_v1"} for a in AGENT_IDS],
            "timing": {"mode": "barrier", "decision_window_ms": 5000},
            "horizon_ticks": 30,
        }
    )
    run_id = create_run(store, config).run_id
    summary = asyncio.run(Coordinator(store, run_id, build_policies(config)).run())

    paths = write_transcripts(store, run_id, tmp_path / "out")
    assert [p.name for p in paths] == ["A.jsonl", "B.jsonl", "C.jsonl"]
    for path in paths:
        entries = [TranscriptEntry.model_validate_json(line) for line in path.read_text().splitlines()]
        assert [e.tick for e in entries] == list(range(1, summary.committed_tick + 1))
        for before, after in pairwise(entries):
            assert after.spectator.position_before == before.spectator.position_after
            assert after.observation is not None and after.observation.notebook == before.notebook_after
        for e in entries:
            assert e.observation is not None and e.observation.decision_tick == e.tick
            assert e.outcome.tick == e.tick and e.agent_id == path.stem

    out = tmp_path / "run.zip"
    export_run(store, run_id, out)
    assert verify_export(out)
    with zipfile.ZipFile(out) as zf:
        assert {"transcripts/A.jsonl", "transcripts/B.jsonl", "transcripts/C.jsonl"} <= set(zf.namelist())
    store.close()
