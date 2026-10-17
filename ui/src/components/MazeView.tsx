import { useRef, useState, type KeyboardEvent } from "react";
import { AGENT_IDS } from "../api/types";
import type { AgentId, CellDef, Edge, MazeDefinition, WorldState } from "../api/types";
import type { Trails } from "../state/journal";
import { AGENT_COLORS } from "./AgentBadge";

const CELL = 52;
const PAD = 10;
const SIDES = ["north", "east", "south", "west"] as const;
type Side = (typeof SIDES)[number];

// Agent offsets inside a cell, so co-located agents stay distinguishable.
const OFFSET: Record<AgentId, [number, number]> = { A: [-11, -9], B: [11, -9], C: [0, 11] };

interface Props {
  maze: MazeDefinition;
  state: WorldState;
  trails: Trails;
}

function edgeLine(cell: CellDef, side: Side): [number, number, number, number] {
  const x0 = PAD + cell.x * CELL;
  const y0 = PAD + cell.y * CELL;
  const x1 = x0 + CELL;
  const y1 = y0 + CELL;
  if (side === "north") return [x0, y0, x1, y0];
  if (side === "south") return [x0, y1, x1, y1];
  if (side === "west") return [x0, y0, x0, y1];
  return [x1, y0, x1, y1];
}

function edgeClass(edge: Edge): string | null {
  if (edge === "outer_brick") return "wall-brick";
  if (edge === "interior_wall") return "wall-interior";
  return null;
}

export function MazeView({ maze, state, trails }: Props) {
  const [focus, setFocus] = useState({ x: 0, y: 0 });
  const svg = useRef<SVGSVGElement>(null);
  const width = maze.width * CELL + 2 * PAD;
  const height = maze.height * CELL + 2 * PAD;
  const center = (v: number) => PAD + v * CELL + CELL / 2;

  const agentsAt = (x: number, y: number) =>
    state.agents.filter((a) => a.position.x === x && a.position.y === y).map((a) => a.agent_id);

  const isExit = (c: { x: number; y: number }) => c.x === maze.exit.x && c.y === maze.exit.y;

  const label = (cell: CellDef) => {
    const edges = SIDES.map((s) => `${s} ${cell[s].replace("_", " ")}`).join(", ");
    const agents = agentsAt(cell.x, cell.y);
    const who = agents.length ? `agents ${agents.join(", ")}` : "no agents";
    return `x ${cell.x}, y ${cell.y}${isExit(cell) ? ", exit" : ""}: ${edges}; ${who}`;
  };

  const onKeyDown = (e: KeyboardEvent) => {
    const step: Record<string, [number, number]> = {
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
    };
    const d = step[e.key];
    if (!d) return;
    e.preventDefault();
    const [x, y] = ((e.target as SVGElement).dataset.cell ?? `${focus.x},${focus.y}`).split(",").map(Number);
    const next = {
      x: Math.min(maze.width - 1, Math.max(0, x + d[0])),
      y: Math.min(maze.height - 1, Math.max(0, y + d[1])),
    };
    setFocus(next);
    svg.current?.querySelector<SVGElement>(`[data-cell="${next.x},${next.y}"]`)?.focus();
  };

  const rows = Array.from({ length: maze.height }, (_, y) => maze.cells.filter((c) => c.y === y));
  const focusedCell = maze.cells.find((c) => c.x === focus.x && c.y === focus.y);
  const groups = new Map<string, AgentId[]>();
  for (const a of state.agents) {
    const key = `${a.position.x},${a.position.y}`;
    groups.set(key, [...(groups.get(key) ?? []), a.agent_id]);
  }

  return (
    <div className="maze">
      <svg ref={svg} viewBox={`0 0 ${width} ${height}`} width={width} height={height} onKeyDown={onKeyDown}>
        <defs>
          <pattern id="brick" width="16" height="8" patternUnits="userSpaceOnUse">
            <rect width="16" height="8" fill="#b5532f" />
            <path d="M0 0H16M0 4H16M4 0V4M12 4V8" stroke="#e8c9a8" strokeWidth="1" />
          </pattern>
        </defs>

        <g role="grid" aria-label="Maze cells; arrow keys move between cells">
          {rows.map((row, y) => (
            <g role="row" key={y}>
              {row.map((cell) => (
                <rect
                  key={`${cell.x},${cell.y}`}
                  role="gridcell"
                  data-cell={`${cell.x},${cell.y}`}
                  tabIndex={cell.x === focus.x && cell.y === focus.y ? 0 : -1}
                  aria-label={label(cell)}
                  onFocus={() => setFocus({ x: cell.x, y: cell.y })}
                  className={isExit(cell) ? "cell cell-exit" : "cell"}
                  x={PAD + cell.x * CELL}
                  y={PAD + cell.y * CELL}
                  width={CELL}
                  height={CELL}
                />
              ))}
            </g>
          ))}
        </g>

        <text className="exit-label" x={center(maze.exit.x)} y={center(maze.exit.y) + CELL / 2 - 5} aria-hidden>
          EXIT
        </text>

        <g aria-hidden>
          {maze.cells.flatMap((cell) =>
            SIDES.map((side) => {
              const cls = edgeClass(cell[side]);
              if (!cls) return null;
              const [x1, y1, x2, y2] = edgeLine(cell, side);
              return <line key={`${cell.x},${cell.y},${side}`} className={cls} x1={x1} y1={y1} x2={x2} y2={y2} />;
            }),
          )}
        </g>

        <g aria-hidden>
          {AGENT_IDS.map((id) => (
            <polyline
              key={id}
              className="trail"
              stroke={AGENT_COLORS[id]}
              points={trails[id].map((p) => `${center(p.x) + OFFSET[id][0] / 2},${center(p.y) + OFFSET[id][1] / 2}`).join(" ")}
            />
          ))}
        </g>

        <g aria-hidden>
          {[...groups.entries()]
            .filter(([, ids]) => ids.length > 1)
            .map(([key]) => {
              const [x, y] = key.split(",").map(Number);
              return <circle key={key} className="meeting" cx={center(x)} cy={center(y)} r={CELL / 2 - 3} />;
            })}
          {state.agents.map((a) => (
            <g key={a.agent_id} transform={`translate(${center(a.position.x) + OFFSET[a.agent_id][0]},${center(a.position.y) + OFFSET[a.agent_id][1]})`}>
              <circle r="10" fill={AGENT_COLORS[a.agent_id]} stroke="#fff" strokeWidth="1.5" />
              <text className="agent-letter" y="4">
                {a.agent_id}
              </text>
            </g>
          ))}
        </g>
      </svg>
      <p className="cell-readout" aria-live="polite">
        Focused cell: {focusedCell ? label(focusedCell) : "none"}
      </p>
    </div>
  );
}
