import { describe, expect, it } from "vitest";
import type { EventEnvelope, EventPayload, WorldState } from "../api/types";
import { heardAtDecision, nextEventTick, radioRecords, trailsUpTo, JUMP_KINDS } from "./journal";

const envelope = (sequence: number, tick: number, payload: EventPayload): EventEnvelope => ({
  schema_version: "1.0",
  run_id: "r",
  sequence,
  tick,
  type: payload.type,
  recorded_at: "",
  payload,
});

const commitAt = (sequence: number, tick: number, ax: number) =>
  envelope(sequence, tick, {
    type: "tick.committed",
    state: {
      tick,
      agents: [{ agent_id: "A", position: { x: ax, y: 0 } }],
    } as unknown as WorldState,
    metrics: {} as never,
    state_hash: "",
    first_sequence: sequence,
    last_sequence: sequence,
  });

const journal = [
  commitAt(1, 0, 0),
  envelope(2, 1, { type: "radio.sent", sender: "A", sent_tick: 1, visible_decision_tick: 2, recipients: ["B", "C"], text: "hi", utf8_bytes: 2 }),
  commitAt(3, 1, 1),
  commitAt(4, 2, 1),
  envelope(5, 3, { type: "agent.exit_reached", agent_id: "A", tick: 3 }),
  commitAt(6, 3, 2),
];

describe("journal views", () => {
  it("builds trails up to the displayed tick", () => {
    expect(trailsUpTo(journal, 2).A).toEqual([{ x: 0, y: 0 }, { x: 1, y: 0 }]);
    expect(trailsUpTo(journal, 3).A).toHaveLength(3);
  });

  it("marks radio as heard only at the decision after it was sent", () => {
    const [record] = radioRecords(journal);
    expect(record.sequence).toBe(2);
    expect(heardAtDecision(record, 1)).toEqual([]);
    expect(heardAtDecision(record, 2)).toEqual(["B", "C"]);
    expect(heardAtDecision(record, 3)).toEqual([]);
  });

  it("finds the next exit event after the current tick", () => {
    expect(nextEventTick(journal, 0, JUMP_KINDS.exit)).toBe(3);
    expect(nextEventTick(journal, 3, JUMP_KINDS.exit)).toBeNull();
  });
});
