import type { components } from "./schema";

type S = components["schemas"];

export type AgentId = "A" | "B" | "C";
export const AGENT_IDS: AgentId[] = ["A", "B", "C"];

export type RunSummary = S["RunSummary"];
export type RunDetail = S["RunDetail"];
export type RunStatus = RunSummary["status"];
export type MazeDefinition = S["MazeDefinition"];
export type CellDef = S["CellDef"];
export type Edge = CellDef["north"];
export type Position = S["Position"];
export type StateResponse = S["StateResponse"];
export type TickSnapshot = S["TickSnapshot"];
export type WorldState = S["WorldState"];
export type AgentState = S["AgentState"];
export type RunMetrics = S["RunMetrics"];
export type AgentMetrics = S["AgentMetrics"];
export type ObservationResponse = S["ObservationResponse"];
export type Observation = S["Observation"];
export type ActionReceipt = S["ActionReceipt"];
export type NotebookRevision = S["NotebookRevision"];
export type RadioRecord = S["RadioRecord"];
export type InvocationRecord = S["InvocationRecord"];
export type EventEnvelope = S["EventEnvelope"];
export type EventPayload = EventEnvelope["payload"];
export type CommandReceipt = S["CommandReceipt"];
export type RunCommand = S["RunCommand"];

export const EVENT_TYPES: EventPayload["type"][] = [
  "agent.decision_resolved",
  "notebook.updated",
  "radio.sent",
  "meeting.observed",
  "agent.exit_reached",
  "tick.committed",
  "run.status_changed",
  "run.created",
  "run.completed",
];

export const TERMINAL_STATUSES: RunStatus[] = ["completed", "cancelled", "failed"];
