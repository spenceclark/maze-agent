"""Spectator API contract tests (spec §11, §17): viewer-independent runs, consistent
reads, idempotent commands, and SSE/WebSocket parity."""

import json
import time
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from maze_lab.agent_contracts import AGENT_IDS
from maze_lab.api.app import create_app

API = "/api/v1"


def baseline_config(mode: str = "barrier", horizon: int = 120) -> dict[str, object]:
    return {
        "root_seed": 5,
        "condition": "api_test",
        "maze": {"width": 5, "height": 5},
        "agents": [{"id": a, "kind": "baseline", "policy": "dfs_bounded_v1"} for a in AGENT_IDS],
        "timing": {"mode": mode, "decision_window_ms": 2000},
        "horizon_ticks": horizon,
    }


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(tmp_path / "api.db")) as c:
        yield c


def command(client: TestClient, run_id: str, name: str, key: str, expected_tick: int = 0):
    return client.post(
        f"{API}/runs/{run_id}/commands",
        json={"command": name, "expected_state_tick": expected_tick},
        headers={"Idempotency-Key": key},
    )


def wait_for(client: TestClient, run_id: str, status: str, timeout: float = 20) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        summary = client.get(f"{API}/runs/{run_id}").json()["summary"]
        if summary["status"] == status:
            return summary
        time.sleep(0.05)
    raise AssertionError(f"run never reached {status}")


def completed_run(client: TestClient) -> str:
    run_id = client.post(f"{API}/runs", json=baseline_config()).json()["run_id"]
    assert command(client, run_id, "start", "k1").status_code == 202
    wait_for(client, run_id, "completed")
    return run_id


def test_run_completes_without_any_viewer_and_reads_are_consistent(client: TestClient):
    run_id = completed_run(client)
    state = client.get(f"{API}/runs/{run_id}/state").json()
    tick = state["state_tick"]
    assert state["snapshot"]["state"]["tick"] == tick and tick > 0
    assert state["as_of_sequence"] >= state["snapshot"]["last_sequence"]

    historical = client.get(f"{API}/runs/{run_id}/state", params={"at_tick": 1}).json()
    assert (
        historical["state_tick"] == 1
        and historical["as_of_sequence"] == historical["snapshot"]["last_sequence"]
    )
    assert client.get(f"{API}/runs/{run_id}/state", params={"at_tick": tick + 1}).status_code == 409

    agents = client.get(f"{API}/runs/{run_id}/agents", params={"at_tick": 1}).json()["agents"]
    notebook = client.get(f"{API}/runs/{run_id}/agents/A/notebook", params={"at_tick": 1}).json()["notebook"]
    assert notebook == agents[0]["notebook"]

    obs = client.get(f"{API}/runs/{run_id}/agents/B/observation", params={"decision_tick": 1}).json()
    assert obs["observation"]["agent_id"] == "B" and obs["observation"]["decision_tick"] == 1

    metrics = client.get(f"{API}/runs/{run_id}/metrics").json()["metrics"]
    assert metrics["objective_met_tick"] == tick

    replay = client.get(f"{API}/runs/{run_id}/replay", params={"at_tick": 2}).json()
    assert replay["snapshot"]["tick"] == 2 and replay["available_ticks"] == [0, tick]


def test_maze_etag(client: TestClient):
    run_id = client.post(f"{API}/runs", json=baseline_config()).json()["run_id"]
    first = client.get(f"{API}/runs/{run_id}/maze")
    etag = first.headers["etag"]
    assert etag == f'"{first.json()["maze_hash"]}"'
    assert client.get(f"{API}/runs/{run_id}/maze", headers={"If-None-Match": etag}).status_code == 304


def test_commands_are_idempotent_and_versioned(client: TestClient):
    run_id = client.post(f"{API}/runs", json=baseline_config(mode="manual")).json()["run_id"]
    first = command(client, run_id, "start", "same-key").json()
    again = command(client, run_id, "start", "same-key").json()
    assert first["command_id"] == again["command_id"]
    assert command(client, run_id, "pause", "same-key").status_code == 409  # key reuse, different body
    wait_for(client, run_id, "paused")

    assert command(client, run_id, "step", "s1", expected_tick=5).status_code == 409  # stale tick
    assert command(client, run_id, "resume", "r0", expected_tick=0).status_code == 202
    wait_for(client, run_id, "running")
    receipts = client.get(f"{API}/runs/{run_id}").json()["commands"]
    assert [r["command"] for r in receipts] == ["start", "resume"]
    assert receipts[0]["status"] == "applied"


def test_manual_step_then_cancel(client: TestClient):
    run_id = client.post(f"{API}/runs", json=baseline_config(mode="manual")).json()["run_id"]
    command(client, run_id, "start", "a")
    wait_for(client, run_id, "paused")
    assert command(client, run_id, "step", "b", expected_tick=0).status_code == 202
    deadline = time.monotonic() + 10
    while client.get(f"{API}/runs/{run_id}").json()["summary"]["committed_tick"] < 1:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    assert client.get(f"{API}/runs/{run_id}").json()["summary"]["status"] == "paused"
    assert command(client, run_id, "cancel", "c", expected_tick=1).status_code == 202
    summary = wait_for(client, run_id, "cancelled")
    assert summary["termination_reason"] == "operator_cancelled"


def test_paging_is_stable_and_bound_to_filters(client: TestClient):
    run_id = completed_run(client)
    seen: list[int] = []
    cursor = None
    while True:
        params: dict[str, str | int] = {"limit": 7}
        if cursor:
            params["cursor"] = cursor
        page = client.get(f"{API}/runs/{run_id}/timeline", params=params).json()
        seen += [e["sequence"] for e in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == list(range(1, len(seen) + 1))
    first = client.get(f"{API}/runs/{run_id}/agents/A/notebook-revisions", params={"limit": 1}).json()
    assert first["next_cursor"] is not None
    wrong = client.get(f"{API}/runs/{run_id}/radio", params={"cursor": first["next_cursor"]})
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "invalid_cursor"


def test_errors_use_the_envelope(client: TestClient):
    missing = client.get(f"{API}/runs/nope/state")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    bad = client.post(f"{API}/runs", json={"root_seed": 1})
    assert bad.status_code == 422 and "error" in bad.json()


def test_export_zip_has_checksums(client: TestClient):
    run_id = completed_run(client)
    data = client.get(f"{API}/runs/{run_id}/export").content
    with zipfile.ZipFile(BytesIO(data)) as zf:
        assert {"manifest.json", "maze.json", "events.ndjson", "SHA256SUMS"} <= set(zf.namelist())


def _sse_envelopes(client: TestClient, run_id: str, after: int = 0) -> list[dict[str, object]]:
    envelopes = []
    with client.stream("GET", f"{API}/runs/{run_id}/events", params={"after_sequence": after}) as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                envelopes.append(json.loads(line.removeprefix("data: ")))
    return envelopes


def test_sse_and_websocket_carry_identical_envelopes(client: TestClient):
    run_id = completed_run(client)
    sse = _sse_envelopes(client, run_id)
    assert [e["sequence"] for e in sse] == list(range(1, len(sse) + 1))
    assert sse[-1]["type"] == "run.completed"

    ws_items = []
    with client.websocket_connect(f"{API}/runs/{run_id}/ws?after_sequence=0") as ws:
        while True:
            item = ws.receive_json()
            ws_items.append(item)
            if item["type"] == "run.completed":
                break
    assert ws_items == sse


def test_reconnect_resumes_after_last_event_id(client: TestClient):
    run_id = completed_run(client)
    full = _sse_envelopes(client, run_id)
    resumed = _sse_envelopes(client, run_id, after=10)
    assert resumed == full[10:]
    assert _sse_envelopes(client, run_id, after=len(full) + 50) == []  # finished run: stream closes


def test_tokens_gate_reads_and_mutations(tmp_path: Path):
    app = create_app(tmp_path / "auth.db", spectator_token="spec", operator_token="op")
    with TestClient(app) as c:
        assert c.get(f"{API}/runs").status_code == 401
        assert c.get(f"{API}/runs", headers={"Authorization": "Bearer spec"}).status_code == 200
        created = c.post(f"{API}/runs", json=baseline_config(), headers={"Authorization": "Bearer spec"})
        assert created.status_code == 403
        created = c.post(f"{API}/runs", json=baseline_config(), headers={"Authorization": "Bearer op"})
        assert created.status_code == 201
        assert c.get("/health/live").status_code == 200
