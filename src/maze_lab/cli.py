"""Headless command line: create and run experiments, verify and export them."""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import get_args

from dotenv import find_dotenv, load_dotenv

from maze_lab.agent_contracts import AGENT_IDS
from maze_lab.config import BaselineAgentConfig, BaselinePolicyName, RunConfig, TimingConfig, TimingMode
from maze_lab.coordinator import Coordinator
from maze_lab.export import export_run
from maze_lab.persistence.store import RunStore
from maze_lab.replay import verify_run
from maze_lab.runs import build_policies, create_run
from maze_lab.transcript import write_transcripts


def _config_from_args(args: argparse.Namespace) -> RunConfig:
    if args.config:
        return RunConfig.model_validate_json(Path(args.config).read_text(encoding="utf-8"))
    data: dict[str, object] = {
        "root_seed": args.seed,
        "condition": f"baseline_{args.policy}",
        "maze": {"width": args.size, "height": args.size},
        "agents": [BaselineAgentConfig(id=a, kind="baseline", policy=args.policy) for a in AGENT_IDS],
        "timing": TimingConfig(mode=args.mode, decision_window_ms=args.window_ms),
    }
    if args.horizon is not None:
        data["horizon_ticks"] = args.horizon
    return RunConfig.model_validate(data)


def _print(obj: object) -> None:
    print(json.dumps(obj, indent=2, default=str))


async def _drive(store: RunStore, run_id: str) -> None:
    config = store.config(run_id)
    summary = await Coordinator(store, run_id, build_policies(config)).run()
    final = store.tick_commit(run_id, summary.committed_tick)
    _print(
        {
            "summary": summary.model_dump(mode="json"),
            "metrics": final.metrics.model_dump(mode="json") if final else None,
        }
    )


def _write_schemas(out: Path) -> None:
    """Published contracts: the API (OpenAPI) and what agents see and emit (JSON Schema)."""
    from maze_lab.agent_contracts import AgentRules, Observation, TurnAction
    from maze_lab.api.app import create_app

    out.mkdir(parents=True, exist_ok=True)
    documents = {
        "openapi.json": create_app(":memory:").openapi(),
        "observation.schema.json": Observation.model_json_schema(),
        "turn_action.schema.json": TurnAction.model_json_schema(),
        "agent_rules.schema.json": AgentRules.model_json_schema(),
        "run_config.schema.json": RunConfig.model_json_schema(),
    }
    for name, doc in documents.items():
        (out / name).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out / name}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maze-lab", description=__doc__)
    parser.add_argument("--db", default="runs.db", help="SQLite run database (default: runs.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="create a run and drive it to completion")
    run.add_argument("--config", help="RunConfig JSON file; otherwise a baseline run is built from flags")
    run.add_argument("--seed", type=int, default=20261017)
    run.add_argument("--policy", choices=get_args(BaselinePolicyName), default="dfs_bounded_v1")
    run.add_argument("--size", type=int, default=15)
    run.add_argument("--horizon", type=int, help="default scales with maze size (500 ticks for 15x15)")
    run.add_argument("--mode", choices=get_args(TimingMode), default="barrier")
    run.add_argument("--window-ms", type=int, default=60_000)

    for name, help_text in (
        ("resume", "continue a run (recovers an interrupted tick)"),
        ("verify", "re-execute recorded actions and check every state hash"),
        ("show", "print a run's summary and latest metrics"),
    ):
        sub.add_parser(name, help=help_text).add_argument("run_id")
    transcript = sub.add_parser("transcript", help="write one JSONL file per agent, one line per turn")
    transcript.add_argument("run_id")
    transcript.add_argument("--out", type=Path, help="output directory (default: transcripts/<run_id>)")
    export = sub.add_parser("export", help="write a replay ZIP with checksums")
    export.add_argument("run_id")
    export.add_argument("out", type=Path)
    sub.add_parser("list", help="list runs")
    schema = sub.add_parser("schema", help="write OpenAPI and agent-contract JSON Schemas")
    schema.add_argument("--out", type=Path, default=Path("schemas"))
    serve = sub.add_parser("serve", help="run the spectator API (single process; owns all coordinators)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    load_dotenv(find_dotenv(usecwd=True))  # provider keys stay server-side, referenced by env var name
    store = RunStore(args.db)
    try:
        match args.command:
            case "run":
                summary = create_run(store, _config_from_args(args))
                print(f"created run {summary.run_id}", file=sys.stderr)
                asyncio.run(_drive(store, summary.run_id))
            case "resume":
                asyncio.run(_drive(store, args.run_id))
            case "verify":
                report = verify_run(store, args.run_id)
                _print(
                    {
                        "ok": report.ok,
                        "ticks_checked": report.ticks_checked,
                        "mismatched": report.mismatched_ticks,
                    }
                )
                return 0 if report.ok else 1
            case "show":
                summary = store.summary(args.run_id)
                if summary is None:
                    print(f"no such run: {args.run_id}", file=sys.stderr)
                    return 1
                final = store.tick_commit(args.run_id, summary.committed_tick)
                _print(
                    {
                        "summary": summary.model_dump(mode="json"),
                        "metrics": final.metrics.model_dump(mode="json") if final else None,
                    }
                )
            case "transcript":
                for path in write_transcripts(
                    store, args.run_id, args.out or Path("transcripts") / args.run_id
                ):
                    print(f"wrote {path}", file=sys.stderr)
            case "export":
                export_run(store, args.run_id, args.out)
                print(f"wrote {args.out}", file=sys.stderr)
            case "serve":
                import uvicorn

                from maze_lab.api.app import create_app

                store.close()
                uvicorn.run(create_app(args.db), host=args.host, port=args.port, workers=1)
            case "schema":
                _write_schemas(args.out)
            case "list":
                for s in store.summaries():
                    print(f"{s.run_id}  {s.status:<9}  tick {s.committed_tick:>4}  {s.condition}")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
