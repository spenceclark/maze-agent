import type { RadioRecord } from "../api/types";
import { heardAtDecision } from "../state/journal";
import { AgentBadge } from "./AgentBadge";

interface Props {
  records: RadioRecord[];
  tick: number;
}

export function RadioPanel({ records, tick }: Props) {
  const decision = tick + 1;
  return (
    <section className="panel">
      <h3>Radio archive</h3>
      <p className="muted">
        At state tick {tick}, the next decision is tick {decision}: agents hear messages sent at tick {tick}.
      </p>
      <table className="radio">
        <thead>
          <tr>
            <th>Seq</th>
            <th>From</th>
            <th>Sent</th>
            <th>Heard at decision</th>
            <th>Heard now by</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody>
          {records.map((r) => {
            const heard = heardAtDecision(r, decision);
            return (
              <tr key={r.sequence} className={heard.length ? "heard" : r.sent_tick > tick ? "future" : undefined}>
                <td>{r.sequence}</td>
                <td>
                  <AgentBadge id={r.sender} />
                </td>
                <td>{r.sent_tick}</td>
                <td>{r.visible_decision_tick}</td>
                <td>{heard.length ? heard.map((a) => <AgentBadge key={a} id={a} />) : <span className="muted">—</span>}</td>
                <td className="message">{r.text}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
