import type {
  AgentId,
  CommandReceipt,
  EventEnvelope,
  InvocationRecord,
  MazeDefinition,
  NotebookRevision,
  ObservationResponse,
  RadioRecord,
  RunCommand,
  RunDetail,
  RunSummary,
  StateResponse,
} from "./types";

const BASE = "/api/v1";

type Query = Record<string, string | number | string[] | undefined | null>;

interface Page<T> {
  items: T[];
  next_cursor?: string | null;
  as_of_sequence: number;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

function url(path: string, query: Query = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    for (const v of Array.isArray(value) ? value : [value]) params.append(key, String(v));
  }
  const qs = params.toString();
  return `${BASE}${path}${qs ? `?${qs}` : ""}`;
}

async function request<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = body?.error ?? { code: String(response.status), message: response.statusText };
    throw new ApiError(response.status, error.code, error.message);
  }
  return body as T;
}

const get = <T>(path: string, query?: Query) => request<T>(url(path, query));

async function allPages<T>(path: string, query: Query = {}): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | null | undefined;
  do {
    const page = await get<Page<T>>(path, { ...query, cursor, limit: 1000 });
    items.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor);
  return items;
}

const run = (id: string) => `/runs/${encodeURIComponent(id)}`;

export const api = {
  listRuns: () => allPages<RunSummary>("/runs"),
  getRun: (id: string) => get<RunDetail>(run(id)),
  getMaze: (id: string) => get<MazeDefinition>(`${run(id)}/maze`),
  getState: (id: string, atTick?: number) => get<StateResponse>(`${run(id)}/state`, { at_tick: atTick }),
  getObservation: (id: string, agent: AgentId, decisionTick: number) =>
    get<ObservationResponse>(`${run(id)}/agents/${agent}/observation`, { decision_tick: decisionTick }),
  getInvocations: (id: string, agent: AgentId, tick: number) =>
    get<Page<InvocationRecord>>(`${run(id)}/invocations`, { agent, tick }).then((p) => p.items),
  notebookRevisions: (id: string, agent: AgentId) =>
    allPages<NotebookRevision>(`${run(id)}/agents/${agent}/notebook-revisions`),
  radio: (id: string) => allPages<RadioRecord>(`${run(id)}/radio`),
  // ponytail: whole journal held in memory (incl. full state per tick.committed); page by tick range for long runs
  timeline: (id: string) => allPages<EventEnvelope>(`${run(id)}/timeline`),

  sendCommand: (id: string, command: RunCommand["command"], expectedTick: number) =>
    request<CommandReceipt>(url(`${run(id)}/commands`), {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ command, expected_state_tick: expectedTick } satisfies RunCommand),
    }),

  eventsUrl: (id: string, afterSequence: number) => url(`${run(id)}/events`, { after_sequence: afterSequence }),
};
