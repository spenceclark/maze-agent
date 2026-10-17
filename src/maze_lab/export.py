"""Replay export: a checksummed ZIP of everything needed to replay and analyse a run (spec §10)."""

import hashlib
import zipfile
from pathlib import Path

from maze_lab.persistence.store import RunStore
from maze_lab.transcript import transcript_files


def _ndjson(lines: list[str]) -> bytes:
    return "".join(line + "\n" for line in lines).encode()


def export_run(store: RunStore, run_id: str, path: Path) -> None:
    """ZIP replay export with a SHA-256 checksum file."""
    files: dict[str, bytes] = {
        "manifest.json": store.manifest(run_id).model_dump_json(indent=2).encode(),
        "maze.json": store.maze(run_id).model_dump_json(indent=2).encode(),
        "events.ndjson": _ndjson([e.model_dump_json() for e in store.events(run_id)]),
        "invocations.ndjson": _ndjson([i.model_dump_json() for i in store.invocations(run_id)]),
        "notebook_revisions.ndjson": _ndjson([r.model_dump_json() for r in store.notebook_revisions(run_id)]),
        "radio.ndjson": _ndjson([r.model_dump_json() for r in store.radio(run_id)]),
    }
    for name, data in transcript_files(store, run_id).items():
        files[f"transcripts/{name}"] = data
    for snap in store.snapshots(run_id):
        files[f"snapshots/{snap.tick:06d}.json"] = snap.model_dump_json().encode()
    summary = store.summary(run_id)
    last = store.tick_commit(run_id, summary.committed_tick) if summary else None
    if last is not None:
        files["metrics.json"] = last.metrics.model_dump_json(indent=2).encode()
    checksums = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(files.items())
    )
    files["SHA256SUMS"] = checksums.encode()

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)


def verify_export(path: Path) -> bool:
    """Check every file in an export against its recorded checksum."""
    with zipfile.ZipFile(path) as zf:
        expected: dict[str, str] = {}
        for line in zf.read("SHA256SUMS").decode().splitlines():
            digest, name = line.split("  ", 1)
            expected[name] = digest
        if set(expected) != set(zf.namelist()) - {"SHA256SUMS"}:
            return False
        return all(hashlib.sha256(zf.read(name)).hexdigest() == digest for name, digest in expected.items())
