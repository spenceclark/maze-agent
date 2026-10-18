import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ActionReceipt, AgentId, AgentState, InvocationRecord, Observation, RunMetrics } from "../api/types";
import { AgentBadge } from "./AgentBadge";

interface Props {
  runId: string;
  agent: AgentState;
  tick: number;
  metrics: RunMetrics;
}

const tenths = (v: number) => (v / 10).toFixed(1);

function ReceiptView({ receipt }: { receipt: ActionReceipt }) {
  const m = receipt.movement;
  const component = (c: ActionReceipt["notebook"]) => (c.code ? `${c.status} (${c.code})` : c.status);
  return (
    <dl className="facts">
      <dt>Action tick</dt>
      <dd>{receipt.tick}</dd>
      <dt>Move</dt>
      <dd>
        {m.attempted ?? "—"} → {m.outcome}
        {m.arrived_from ? `, arrived from ${m.arrived_from}` : ""}
        {m.cause ? ` (cause: ${m.cause})` : ""}
      </dd>
      <dt>Notebook</dt>
      <dd>{component(receipt.notebook)}</dd>
      <dt>Radio</dt>
      <dd>{component(receipt.radio)}</dd>
    </dl>
  );
}

function ObservationView({ obs }: { obs: Observation }) {
  const b = obs.budgets;
  const radioReady = b.radio_enabled && obs.decision_tick >= b.radio_next_eligible_tick;
  return (
    <div className="agent-view">
      <dl className="facts">
        <dt>Local cell</dt>
        <dd>
          N {obs.local.north}, E {obs.local.east}, S {obs.local.south}, W {obs.local.west}
          {obs.local.is_exit ? " — EXIT" : ""}
        </dd>
        <dt>Exit distance</dt>
        <dd>{obs.exit_distance_tenths == null ? "off" : tenths(obs.exit_distance_tenths)}</dd>
        <dt>Peer ranges</dt>
        <dd>
          {obs.peer_ranges == null
            ? "off"
            : obs.peer_ranges.map((p) => `${p.agent_id} ${tenths(p.distance_tenths)}`).join(", ")}
        </dd>
        <dt>Reached exit</dt>
        <dd>{obs.has_reached_exit ? "yes" : "no"}</dd>
        <dt>Radio</dt>
        <dd>
          {radioReady ? "eligible to send" : `cooldown until decision ${b.radio_next_eligible_tick}`} (max{" "}
          {b.radio_message_bytes} B)
        </dd>
        <dt>Notebook</dt>
        <dd>
          rev {obs.notebook.revision}, {obs.notebook.utf8_bytes} / {b.notebook_cap_bytes} B
        </dd>
        <dt>Co-located books</dt>
        <dd>{obs.colocated_notebooks.map((n) => n.owner).join(", ") || "none"}</dd>
      </dl>
      <h5>Last action receipt (as shown to agent)</h5>
      <ReceiptView receipt={obs.last_action} />
      <h5>Radio inbox</h5>
      {obs.radio_inbox.length === 0 ? (
        <p className="muted">empty</p>
      ) : (
        <ul className="inbox">
          {obs.radio_inbox.map((r) => (
            <li key={r.sender}>
              <AgentBadge id={r.sender} /> (sent t{r.sent_tick}) {r.text}
            </li>
          ))}
        </ul>
      )}
      <details>
        <summary>Notebook text in observation</summary>
        <pre className="notebook-text">{obs.notebook.text}</pre>
      </details>
      {obs.colocated_notebooks.map((n) => (
        <details key={n.owner}>
          <summary>Co-located notebook {n.owner}</summary>
          <pre className="notebook-text">{n.text}</pre>
        </details>
      ))}
    </div>
  );
}

function InvocationView({ inv }: { inv: InvocationRecord | null }) {
  if (!inv) return <p className="muted">No invocation recorded for this tick.</p>;
  const usage = inv.attempt?.usage;
  return (
    <dl className="facts">
      <dt>Status</dt>
      <dd>{inv.status}</dd>
      <dt>Latency</dt>
      <dd>{inv.duration_ms != null ? `${Math.round(inv.duration_ms)} ms` : "—"}</dd>
      <dt>Failure</dt>
      <dd className={inv.attempt?.failure ? "error" : ""}>
        {inv.attempt?.failure ?? "none"}
        {inv.attempt?.error_detail ? `: ${inv.attempt.error_detail}` : ""}
      </dd>
      <dt>Tokens</dt>
      <dd>
        {usage?.input_tokens ?? "—"} in / {usage?.output_tokens ?? "—"} out
      </dd>
    </dl>
  );
}

// Observations are only recorded for decisions; a 404 here simply means "none".
function useRecorded<T>(load: () => Promise<T>, deps: unknown[]): T | null {
  const [value, setValue] = useState<T | null>(null);
  useEffect(() => {
    let stale = false;
    setValue(null);
    load().then(
      (v) => !stale && setValue(v),
      () => !stale && setValue(null),
    );
    return () => {
      stale = true;
    };
  }, deps); // load is recreated each render; deps carry its inputs
  return value;
}

export function AgentInspector({ runId, agent, tick, metrics }: Props) {
  const id: AgentId = agent.agent_id;
  // Decision t produced the receipt in state t; decision t+1 is what state t looks like to the agent.
  const [nextDecision, setNextDecision] = useState(true);
  const decisionTick = nextDecision ? tick + 1 : tick;
  // At the head of a run, decision t+1 may not exist (yet); fall back to decision t.
  const obs = useRecorded(
    () => api.getObservation(runId, id, decisionTick).catch(() => api.getObservation(runId, id, tick)),
    [runId, id, decisionTick, tick],
  );
  const inv = useRecorded(() => api.getInvocations(runId, id, tick).then((items) => items.at(-1) ?? null), [runId, id, tick]);
  const m = metrics.agents[id];

  return (
    <section className="panel inspector">
      <h3>
        <AgentBadge id={id} /> Agent {id}
      </h3>

      <h4 className="spectator">Spectator facts (ground truth, hidden from agent)</h4>
      <dl className="facts">
        <dt>Position</dt>
        <dd>
          x {agent.position.x}, y {agent.position.y}
        </dd>
        <dt>Exit reached</dt>
        <dd>{agent.first_exit_tick != null ? `tick ${agent.first_exit_tick}` : "not yet"}</dd>
        <dt>Last radio sent</dt>
        <dd>{agent.last_radio_tick != null ? `tick ${agent.last_radio_tick}` : "never"}</dd>
        <dt>Notebook</dt>
        <dd>
          rev {agent.notebook.revision}, {agent.notebook.utf8_bytes} / {m?.notebook_cap_bytes ?? "?"} B
        </dd>
      </dl>
      <h5>Last action (tick {agent.last_receipt.tick})</h5>
      <ReceiptView receipt={agent.last_receipt} />
      <h5>Decision for tick {tick}: latency and errors</h5>
      <InvocationView inv={inv} />

      <h4 className="agent-visible">Agent view (exact recorded observation)</h4>
      <label className="toggle">
        <input type="checkbox" checked={nextDecision} onChange={(e) => setNextDecision(e.target.checked)} />
        Next decision (built from this tick&apos;s state); untick for the decision that led here
      </label>
      {obs ? (
        <>
          <p className="muted">
            Observation for decision tick {obs.decision_tick} (state tick {obs.decision_tick - 1})
          </p>
          <ObservationView obs={obs.observation} />
        </>
      ) : (
        <p className="muted">No recorded observation.</p>
      )}
    </section>
  );
}
