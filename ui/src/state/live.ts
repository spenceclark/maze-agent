// Pure live-stream reducer (spec §11.3).
// Bootstrap from GET /state, then apply streamed envelopes in sequence order.
// Tick facts are buffered until that tick's `tick.committed`, which replaces the
// displayed dynamic state in one step. Duplicates are dropped; a gap or a
// server `resync` frame flags the state so the caller re-bootstraps.

import { TERMINAL_STATUSES } from "../api/types";
import type { EventEnvelope, RunMetrics, RunStatus, StateResponse, WorldState } from "../api/types";

export interface Committed {
  tick: number;
  state: WorldState;
  metrics: RunMetrics;
}

export interface LiveState {
  runId: string;
  committed: Committed;
  status: RunStatus;
  lastSequence: number;
  pending: EventEnvelope[];
  // Events released by the latest commit (its buffered facts plus the commit itself).
  released: EventEnvelope[];
  needsResync: boolean;
}

export function bootstrap(response: StateResponse, status: RunStatus): LiveState {
  const { snapshot } = response;
  return {
    runId: response.run_id,
    committed: { tick: snapshot.tick, state: snapshot.state, metrics: snapshot.metrics },
    status,
    lastSequence: response.as_of_sequence,
    pending: [],
    released: [],
    needsResync: false,
  };
}

export function applyEvent(live: LiveState, event: EventEnvelope): LiveState {
  if (live.needsResync || event.run_id !== live.runId) return live;
  if (event.sequence <= live.lastSequence) return live; // duplicate after reconnect
  if (event.sequence !== live.lastSequence + 1) return { ...live, needsResync: true };

  const next = { ...live, lastSequence: event.sequence };
  const payload = event.payload;
  switch (payload.type) {
    case "tick.committed":
      return {
        ...next,
        committed: { tick: payload.state.tick, state: payload.state, metrics: payload.metrics },
        pending: [],
        released: [...live.pending, event],
      };
    // Run status is run-level, not per-tick state: show it immediately so a pause is visible.
    case "run.status_changed":
      return { ...next, status: payload.new, released: [event] };
    case "run.completed":
      return { ...next, status: "completed", released: [event] };
    default:
      return { ...next, pending: [...live.pending, event] };
  }
}

export function markResync(live: LiveState): LiveState {
  return { ...live, needsResync: true };
}

// Merge event lists by sequence, dropping duplicates; result is sequence-ordered.
export function mergeEvents(existing: EventEnvelope[], incoming: EventEnvelope[]): EventEnvelope[] {
  if (incoming.length === 0) return existing;
  const bySequence = new Map(existing.map((e) => [e.sequence, e]));
  for (const e of incoming) bySequence.set(e.sequence, e);
  return [...bySequence.values()].sort((a, b) => a.sequence - b.sequence);
}

export type Mode = "LIVE" | "REPLAY";

// What the screen shows: the live head while following, otherwise a locally fetched tick.
// Seeking never touches the live state, so the simulation keeps advancing underneath.
export function displayed(
  live: LiveState | null,
  followLive: boolean,
  historical: Committed | null,
): { view: Committed | null; mode: Mode } {
  const running = live !== null && !TERMINAL_STATUSES.includes(live.status);
  if (followLive && live) return { view: live.committed, mode: running ? "LIVE" : "REPLAY" };
  return { view: historical ?? live?.committed ?? null, mode: "REPLAY" };
}
