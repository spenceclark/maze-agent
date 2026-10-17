import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { RunSummary } from "../api/types";

interface Props {
  selected: string | null;
  onSelect: (runId: string) => void;
}

export function RunPicker({ selected, onSelect }: Props) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    api.listRuns().then(
      (r) => {
        setRuns(r.sort((a, b) => b.created_at.localeCompare(a.created_at)));
        setError(null);
      },
      (e) => setError(String(e.message ?? e)),
    );

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="run-picker">
      <label>
        Run{" "}
        <select value={selected ?? ""} onChange={(e) => onSelect(e.target.value)}>
          <option value="" disabled>
            choose a run…
          </option>
          {runs.map((r) => (
            <option key={r.run_id} value={r.run_id}>
              {r.run_id} · {r.status} · {r.condition} · tick {r.committed_tick}
            </option>
          ))}
        </select>
      </label>
      <button onClick={refresh}>Refresh</button>
      {error && <span className="error">{error}</span>}
    </div>
  );
}
