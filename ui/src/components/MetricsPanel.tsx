import { AGENT_IDS } from "../api/types";
import type { AgentMetrics, RunMetrics } from "../api/types";
import { AgentBadge } from "./AgentBadge";

const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(0)}%`);
const num = (v: number | null | undefined) => (v == null ? "—" : String(v));
const usd = (v: number | null | undefined) => (v == null ? "—" : `$${v.toFixed(4)}`);

const ROWS: [string, (m: AgentMetrics) => string][] = [
  ["First exit tick", (m) => num(m.first_exit_tick)],
  ["Successful moves", (m) => num(m.successful_moves)],
  ["Shortest path to exit", (m) => num(m.shortest_path_to_exit)],
  ["Moves to first exit", (m) => num(m.moves_to_first_exit)],
  ["Path efficiency", (m) => pct(m.path_efficiency)],
  ["Revisits", (m) => `${m.revisits} (${pct(m.revisit_fraction)})`],
  ["Blocked / stayed", (m) => `${m.blocked} / ${m.stayed}`],
  ["Forced stays", (m) => num(m.forced_stays)],
  ["Timeouts", (m) => num(m.forced_stays_by_cause.timeout)],
  ["Valid decisions", (m) => `${m.valid_decisions} / ${m.scheduled_decisions}`],
  ["Radio sent (bytes)", (m) => `${m.radio_accepted} (${m.radio_bytes} B)`],
  ["Notebook bytes / cap", (m) => `${m.notebook_bytes} / ${m.notebook_cap_bytes} (${pct(m.notebook_cap_pressure)})`],
  ["Notebook revisions", (m) => num(m.notebook_revisions)],
  ["Tokens in / out", (m) => `${num(m.input_tokens)} / ${num(m.output_tokens)}`],
  ["Provider requests", (m) => num(m.provider_requests)],
  ["Estimated cost", (m) => usd(m.estimated_cost_usd)],
];

export function MetricsPanel({ metrics }: { metrics: RunMetrics }) {
  const costs = AGENT_IDS.map((id) => metrics.agents[id]?.estimated_cost_usd);
  const totalCost = costs.every((c) => c == null) ? null : costs.reduce<number>((sum, c) => sum + (c ?? 0), 0);
  return (
    <section className="panel">
      <h3>Metrics at tick {metrics.tick}</h3>
      <dl className="facts">
        <dt>Coverage</dt>
        <dd>
          {metrics.covered_cells} / {metrics.reachable_cells} cells ({pct(metrics.coverage)}), shared {metrics.shared_cells},
          redundant {pct(metrics.redundant_exploration)}
        </dd>
        <dt>Exit progress</dt>
        <dd>
          first exit {num(metrics.first_exit_tick)}, objective met {num(metrics.objective_met_tick)}, oracle {metrics.oracle_ticks} ticks
        </dd>
        <dt>Meetings</dt>
        <dd>
          {Object.entries(metrics.meetings)
            .map(([pair, m]) => `${pair}: ${m.episodes} episodes / ${m.colocated_ticks} ticks`)
            .join("; ")}
        </dd>
        <dt>Estimated cost</dt>
        <dd>{usd(totalCost)}</dd>
      </dl>
      <table className="metrics">
        <thead>
          <tr>
            <th>Metric</th>
            {AGENT_IDS.map((id) => (
              <th key={id}>
                <AgentBadge id={id} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map(([name, fmt]) => (
            <tr key={name}>
              <th>{name}</th>
              {AGENT_IDS.map((id) => (
                <td key={id}>{metrics.agents[id] ? fmt(metrics.agents[id]) : "—"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
