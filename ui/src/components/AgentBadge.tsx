import type { AgentId } from "../api/types";

export const AGENT_COLORS: Record<AgentId, string> = { A: "#d1495b", B: "#2e86de", C: "#2a9d5c" };

export function AgentBadge({ id }: { id: AgentId }) {
  return (
    <span className="agent-badge" style={{ background: AGENT_COLORS[id] }}>
      {id}
    </span>
  );
}
