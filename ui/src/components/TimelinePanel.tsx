import { useEffect, useState } from "react";
import { EVENT_TYPES } from "../api/types";
import type { EventEnvelope } from "../api/types";
import { JUMP_KINDS, isErrorEvent, nextEventTick } from "../state/journal";

interface Props {
  journal: EventEnvelope[];
  tick: number;
  maxTick: number;
  followLive: boolean;
  setFollowLive: (on: boolean) => void;
  seek: (tick: number) => void;
}

const SPEEDS = [1, 2, 5, 10];

function describe(e: EventEnvelope): string {
  const p = e.payload;
  switch (p.type) {
    case "agent.decision_resolved": {
      const m = p.receipt.movement;
      return `${p.agent_id}: ${m.attempted ?? "—"} → ${m.outcome}${m.cause ? ` (${m.cause})` : ""}; notebook ${p.receipt.notebook.status}, radio ${p.receipt.radio.status}`;
    }
    case "notebook.updated":
      return `${p.agent_id}: notebook rev ${p.previous_revision} → ${p.new_revision}`;
    case "radio.sent":
      return `${p.sender} → ${p.recipients.join(",")}: ${p.text}`;
    case "meeting.observed":
      return `${p.agents.join("+")} meet at (${p.position.x}, ${p.position.y})`;
    case "agent.exit_reached":
      return `${p.agent_id} reached the exit`;
    case "tick.committed":
      return `tick ${p.state.tick} committed`;
    case "run.status_changed":
      return `status ${p.previous} → ${p.new}${p.reason ? ` (${p.reason})` : ""}`;
    case "run.completed":
      return `run completed: ${p.reason}`;
    case "run.created":
      return "run created";
  }
}

export function TimelinePanel({ journal, tick, maxTick, followLive, setFollowLive, seek }: Props) {
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(2);
  const [shown, setShown] = useState(() => new Set<string>(EVENT_TYPES.filter((t) => t !== "tick.committed")));

  // Local playback only: advances the viewer, never the simulation.
  useEffect(() => {
    if (!playing || followLive) return;
    if (tick >= maxTick) {
      setPlaying(false);
      return;
    }
    const timer = setTimeout(() => seek(tick + 1), 1000 / speed);
    return () => clearTimeout(timer);
  }, [playing, followLive, tick, maxTick, speed, seek]);

  const go = (t: number) => seek(Math.max(0, Math.min(maxTick, t)));
  const jump = (kind: keyof typeof JUMP_KINDS) => {
    const target = nextEventTick(journal, tick, JUMP_KINDS[kind]);
    if (target !== null) go(target);
  };
  const toggleType = (type: string) => {
    const next = new Set(shown);
    if (next.has(type)) next.delete(type);
    else next.add(type);
    setShown(next);
  };
  const events = journal.filter((e) => shown.has(e.type));

  return (
    <section className="panel timeline">
      <h3>Timeline (local playback — does not affect the simulation)</h3>
      <div className="controls">
        <button onClick={() => setPlaying(!playing)} disabled={followLive && !playing} title="Untick Follow live to play back">
          {playing ? "Pause playback" : "Play"}
        </button>
        <button onClick={() => go(tick - 1)} disabled={tick <= 0}>
          ◀ Step
        </button>
        <button onClick={() => go(tick + 1)} disabled={tick >= maxTick}>
          Step ▶
        </button>
        <label>
          Speed{" "}
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
            {SPEEDS.map((s) => (
              <option key={s} value={s}>
                {s} ticks/s
              </option>
            ))}
          </select>
        </label>
        <label className="toggle">
          <input type="checkbox" checked={followLive} onChange={(e) => setFollowLive(e.target.checked)} /> Follow live
        </label>
      </div>
      <div className="controls">
        <input
          type="range"
          className="scrubber"
          min={0}
          max={maxTick}
          value={tick}
          aria-label="Scrub to tick"
          onChange={(e) => go(Number(e.target.value))}
        />
        <span>
          tick {tick} / {maxTick}
        </span>
      </div>
      <div className="controls">
        <span>Jump to next:</span>
        <button onClick={() => jump("meeting")}>Meeting</button>
        <button onClick={() => jump("exit")}>Exit</button>
        <button onClick={() => jump("error")}>Error</button>
      </div>
      <fieldset className="filters">
        <legend>Event types</legend>
        {EVENT_TYPES.map((type) => (
          <label key={type}>
            <input type="checkbox" checked={shown.has(type)} onChange={() => toggleType(type)} /> {type}
          </label>
        ))}
      </fieldset>
      <ol className="events">
        {events.map((e) => (
          <li key={e.sequence} className={[e.tick === tick ? "current" : "", isErrorEvent(e) ? "error" : ""].join(" ")}>
            <button className="link" onClick={() => go(e.tick)}>
              t{e.tick}
            </button>{" "}
            <span className="muted">#{e.sequence}</span> {describe(e)}
          </li>
        ))}
      </ol>
    </section>
  );
}
