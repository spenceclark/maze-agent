import { describe, expect, it } from "vitest";
import type { EventEnvelope, EventPayload, RunMetrics, StateResponse, WorldState } from "../api/types";
import { applyEvent, bootstrap, displayed, markResync, mergeEvents, type LiveState } from "./live";

const RUN = "run1";

// Minimal stand-ins: the reducer only reads `tick` from these.
const world = (tick: number) => ({ tick, agents: [] }) as unknown as WorldState;
const metrics = (tick: number) => ({ tick }) as unknown as RunMetrics;

function stateResponse(tick: number, asOf: number): StateResponse {
  return {
    run_id: RUN,
    state_tick: tick,
    as_of_sequence: asOf,
    pending_commands: [],
    snapshot: { tick, state: world(tick), metrics: metrics(tick) } as StateResponse["snapshot"],
  };
}

function envelope(sequence: number, tick: number, payload: EventPayload, runId = RUN): EventEnvelope {
  return { schema_version: "1.0", run_id: runId, sequence, tick, type: payload.type, recorded_at: "", payload };
}

const exitReached = (seq: number, tick: number) =>
  envelope(seq, tick, { type: "agent.exit_reached", agent_id: "A", tick });

const commit = (seq: number, tick: number) =>
  envelope(seq, tick, {
    type: "tick.committed",
    state: world(tick),
    metrics: metrics(tick),
    state_hash: "h",
    first_sequence: seq - 1,
    last_sequence: seq,
  });

const feed = (live: LiveState, events: EventEnvelope[]) => events.reduce(applyEvent, live);

describe("live follow", () => {
  it("buffers tick facts until tick.committed, then swaps state atomically", () => {
    let live = bootstrap(stateResponse(13, 97), "running");
    live = applyEvent(live, exitReached(98, 14));
    expect(live.committed.tick).toBe(13);
    expect(live.pending).toHaveLength(1);

    live = applyEvent(live, commit(99, 14));
    expect(live.committed.tick).toBe(14);
    expect(live.pending).toEqual([]);
    expect(live.released.map((e) => e.sequence)).toEqual([98, 99]);
    expect(live.lastSequence).toBe(99);
  });

  it("shows status changes immediately and ignores other runs", () => {
    let live = bootstrap(stateResponse(5, 40), "running");
    live = applyEvent(live, envelope(41, 6, { type: "agent.exit_reached", agent_id: "B", tick: 6 }, "other"));
    expect(live.lastSequence).toBe(40);
    live = applyEvent(
      live,
      envelope(41, 5, { type: "run.status_changed", previous: "running", new: "paused", reason: null, effective_tick: 5 }),
    );
    expect(live.status).toBe("paused");
    expect(displayed(live, true, null).mode).toBe("LIVE");
  });
});

describe("historical seek", () => {
  it("shows the fetched tick without touching the live cursor", () => {
    let live = bootstrap(stateResponse(20, 150), "running");
    const historical = { tick: 3, state: world(3), metrics: metrics(3) };

    const seek = displayed(live, false, historical);
    expect(seek.view?.tick).toBe(3);
    expect(seek.mode).toBe("REPLAY");

    // The simulation keeps advancing while the viewer is scrubbed back.
    live = feed(live, [exitReached(151, 21), commit(152, 21)]);
    expect(live.committed.tick).toBe(21);
    expect(displayed(live, false, historical).view?.tick).toBe(3);
    expect(displayed(live, true, historical).view?.tick).toBe(21);
  });

  it("calls a finished run a replay even when following", () => {
    const live = bootstrap(stateResponse(80, 520), "completed");
    expect(displayed(live, true, null).mode).toBe("REPLAY");
  });
});

describe("reconnect with duplicates", () => {
  it("drops already-seen sequences", () => {
    const first = feed(bootstrap(stateResponse(1, 10), "running"), [exitReached(11, 2), commit(12, 2)]);
    // Reconnecting after sequence 10 replays 11..12 before new events arrive.
    const again = feed(first, [exitReached(11, 2), commit(12, 2), exitReached(13, 3), commit(14, 3)]);
    expect(again.needsResync).toBe(false);
    expect(again.lastSequence).toBe(14);
    expect(again.committed.tick).toBe(3);
    expect(again.released.map((e) => e.sequence)).toEqual([13, 14]);
  });

  it("merges journal slices without duplicates", () => {
    const merged = mergeEvents([exitReached(1, 1), commit(2, 1)], [commit(2, 1), exitReached(3, 2)]);
    expect(merged.map((e) => e.sequence)).toEqual([1, 2, 3]);
  });
});

describe("gap and resync", () => {
  it("flags a sequence gap and stops applying events", () => {
    let live = bootstrap(stateResponse(13, 97), "running");
    live = feed(live, [exitReached(98, 14), commit(100, 14)]);
    expect(live.needsResync).toBe(true);
    expect(live.committed.tick).toBe(13);
    expect(applyEvent(live, commit(101, 15))).toBe(live);
  });

  it("re-bootstraps from /state after a resync frame", () => {
    const live = markResync(bootstrap(stateResponse(13, 97), "running"));
    expect(live.needsResync).toBe(true);
    const fresh = bootstrap(stateResponse(30, 220), live.status);
    expect(fresh.needsResync).toBe(false);
    expect(fresh.committed.tick).toBe(30);
    expect(applyEvent(fresh, commit(221, 31)).committed.tick).toBe(31);
  });
});
