// Pure views over the run's event journal (GET /timeline plus live events).

import type { AgentId, EventEnvelope, Position, RadioRecord } from "../api/types";

export type Trails = Record<AgentId, Position[]>;

// Positions after each committed tick up to and including `tick`, consecutive repeats collapsed.
export function trailsUpTo(journal: EventEnvelope[], tick: number): Trails {
  const trails: Trails = { A: [], B: [], C: [] };
  for (const e of journal) {
    if (e.payload.type !== "tick.committed" || e.tick > tick) continue;
    for (const agent of e.payload.state.agents) {
      const trail = trails[agent.agent_id];
      const last = trail[trail.length - 1];
      if (!last || last.x !== agent.position.x || last.y !== agent.position.y) trail.push(agent.position);
    }
  }
  return trails;
}

export function radioRecords(journal: EventEnvelope[]): RadioRecord[] {
  const records: RadioRecord[] = [];
  for (const e of journal) {
    if (e.payload.type !== "radio.sent") continue;
    const { type: _type, ...record } = e.payload;
    records.push({ run_id: e.run_id, sequence: e.sequence, ...record });
  }
  return records;
}

// A message sent at tick t reaches its recipients in the observation for decision t+1,
// which is built from state t. So at a displayed state tick T, the next decision hears T's sends.
export function heardAtDecision(record: RadioRecord, decisionTick: number): AgentId[] {
  return record.visible_decision_tick === decisionTick ? record.recipients : [];
}

export interface Revision {
  revision: number;
  tick: number;
  text: string;
}

export function notebookRevisions(journal: EventEnvelope[], agent: AgentId): Revision[] {
  const revisions: Revision[] = [{ revision: 0, tick: 0, text: "" }];
  for (const e of journal) {
    if (e.payload.type === "notebook.updated" && e.payload.agent_id === agent) {
      revisions.push({ revision: e.payload.new_revision, tick: e.tick, text: e.payload.text });
    }
  }
  return revisions;
}

export function isErrorEvent(e: EventEnvelope): boolean {
  const p = e.payload;
  if (p.type === "agent.decision_resolved") {
    const r = p.receipt;
    return r.movement.outcome === "forced_stay" || r.notebook.status === "rejected" || r.radio.status === "rejected";
  }
  return p.type === "run.status_changed" && p.new === "failed";
}

export const JUMP_KINDS = {
  meeting: (e: EventEnvelope) => e.payload.type === "meeting.observed",
  exit: (e: EventEnvelope) => e.payload.type === "agent.exit_reached",
  error: isErrorEvent,
};

export function nextEventTick(
  journal: EventEnvelope[],
  afterTick: number,
  match: (e: EventEnvelope) => boolean,
): number | null {
  return journal.find((e) => e.tick > afterTick && match(e))?.tick ?? null;
}
