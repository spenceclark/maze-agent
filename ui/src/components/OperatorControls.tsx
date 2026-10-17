import { useState } from "react";
import { api } from "../api/client";
import type { RunCommand, RunStatus } from "../api/types";

interface Props {
  runId: string;
  status: RunStatus;
  liveTick: number;
}

type Command = RunCommand["command"];

const ALLOWED: Record<Command, RunStatus[]> = {
  start: ["created"],
  pause: ["running"],
  resume: ["paused"],
  step: ["paused"],
  cancel: ["created", "running", "paused"],
};

// These change the simulation itself, unlike the timeline's local playback controls.
export function OperatorControls({ runId, status, liveTick }: Props) {
  const [result, setResult] = useState<string | null>(null);

  const send = async (command: Command) => {
    if (command === "cancel" && !confirm("Cancel this run? This cannot be undone.")) return;
    setResult(`${command}: sending…`);
    try {
      // Always the live committed tick, never the scrubbed one.
      const receipt = await api.sendCommand(runId, command, liveTick);
      const after = receipt.effective_after_tick != null ? ` after tick ${receipt.effective_after_tick}` : "";
      setResult(`${command}: ${receipt.status}${after}${receipt.error ? ` — ${receipt.error}` : ""}`);
    } catch (e) {
      setResult(`${command}: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <section className="panel operator">
      <h3>Operator — affects the simulation</h3>
      <div className="controls">
        {(Object.keys(ALLOWED) as Command[]).map((command) => (
          <button key={command} className="danger-outline" disabled={!ALLOWED[command].includes(status)} onClick={() => send(command)}>
            {command[0].toUpperCase() + command.slice(1)} run
          </button>
        ))}
      </div>
      <p className="muted" role="status">
        Run status: {status} at tick {liveTick}
        {result ? ` · ${result}` : ""}
      </p>
    </section>
  );
}
