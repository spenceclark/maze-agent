import { diffWordsWithSpace } from "diff";
import { useState } from "react";
import type { AgentState, EventEnvelope } from "../api/types";
import { notebookRevisions, type Revision } from "../state/journal";
import { AgentBadge } from "./AgentBadge";

interface Props {
  journal: EventEnvelope[];
  agents: AgentState[];
  tick: number;
  liveTick: number | null;
}

// Text is rendered as React children only, so notebook content can never inject markup.
function Diff({ before, after }: { before: string; after: string }) {
  return (
    <pre className="notebook-text">
      {diffWordsWithSpace(before, after).map((part, i) => (
        <span key={i} className={part.added ? "diff-add" : part.removed ? "diff-del" : undefined}>
          {part.value}
        </span>
      ))}
    </pre>
  );
}

function Notebook({ agent, revisions }: { agent: AgentState; revisions: Revision[] }) {
  const current = agent.notebook.revision;
  const [picked, setPicked] = useState<number | null>(null); // null follows the displayed tick
  const [compare, setCompare] = useState<"previous" | "none" | number>("previous");
  const revision = picked !== null && picked <= current ? picked : current;
  const text = revision === current ? agent.notebook.text : (revisions.find((r) => r.revision === revision)?.text ?? "");
  const compareRev = compare === "previous" ? revision - 1 : compare === "none" ? null : compare;
  const before = compareRev === null ? null : revisions.find((r) => r.revision === compareRev);

  return (
    <div className="notebook">
      <h4>
        <AgentBadge id={agent.agent_id} /> Notebook {agent.agent_id}{" "}
        <span className="muted">
          ({agent.notebook.utf8_bytes} B, {agent.notebook.codepoints} chars)
        </span>
      </h4>
      <div className="controls">
        <label>
          Revision{" "}
          <select value={picked === null ? "" : revision} onChange={(e) => setPicked(e.target.value === "" ? null : Number(e.target.value))}>
            <option value="">current at tick (rev {current})</option>
            {revisions.map((r) => (
              <option key={r.revision} value={r.revision}>
                rev {r.revision} (tick {r.tick})
              </option>
            ))}
          </select>
        </label>
        <label>
          Diff against{" "}
          <select
            value={String(compare)}
            onChange={(e) => {
              const v = e.target.value;
              setCompare(v === "previous" || v === "none" ? v : Number(v));
            }}
          >
            <option value="previous">previous revision</option>
            <option value="none">no diff</option>
            {revisions.map((r) => (
              <option key={r.revision} value={r.revision}>
                rev {r.revision}
              </option>
            ))}
          </select>
        </label>
      </div>
      {before ? <Diff before={before.text} after={text} /> : <pre className="notebook-text">{text}</pre>}
    </div>
  );
}

export function NotebookPanel({ journal, agents, tick, liveTick }: Props) {
  const historical = liveTick !== null && tick < liveTick;
  return (
    <section className="panel">
      <h3>Notebooks</h3>
      {historical && (
        <p className="banner warning" role="status">
          Historical view: notebooks as of tick {tick}. The run is at tick {liveTick}.
        </p>
      )}
      <div className="notebooks">
        {agents.map((agent) => (
          <Notebook
            key={agent.agent_id}
            agent={agent}
            revisions={notebookRevisions(journal, agent.agent_id).filter((r) => r.revision <= agent.notebook.revision)}
          />
        ))}
      </div>
    </section>
  );
}
