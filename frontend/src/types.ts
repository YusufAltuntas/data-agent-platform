// Shapes of the API (backend/dap/api/schemas.py) and of the run events (backend/dap/events.py).

export type Role = "viewer" | "analyst" | "admin";

export type RunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "budget_exceeded";

export const TERMINAL_STATUSES: readonly RunStatus[] = [
  "succeeded",
  "failed",
  "cancelled",
  "budget_exceeded",
];

export interface TeamRole {
  id: string;
  name: string;
  role: Role;
}

export interface Me {
  email: string;
  platform_admin: boolean;
  teams: TeamRole[];
}

export interface Dataset {
  id: string;
  name: string;
  description: string;
}

export interface Member {
  team: string;
  email: string;
  role: Role;
}

export interface RunSummary {
  id: string;
  team_id: string;
  dataset_id: string;
  created_by: string;
  question: string;
  status: RunStatus;
  attempts: number;
  cost_usd: number | null;
  created_at: string;
  finished_at: string | null;
}

export interface RunPage {
  items: RunSummary[];
  next_cursor: string | null;
}

/** The `final_answer` tool result (backend/dap/agent/tools.py); `sql` is empty when no query ran. */
export interface Answer {
  answer: string;
  sql: string;
  columns: string[];
  rows: unknown[][];
  truncated: boolean;
}

export interface RunDetail extends RunSummary {
  answer: Answer | null;
  error: string | null;
  model: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  trace_id: string | null;
  started_at: string | null;
}

export interface RunCost {
  id: string;
  created_by: string;
  status: RunStatus;
  cost_usd: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  created_at: string;
}

export interface Budget {
  team: string;
  spend_usd: number | null;
  max_budget_usd: number | null;
  runs: RunCost[];
}

export type EventType = "status" | "llm_call" | "tool_call" | "tool_result" | "answer" | "error";

/** One SSE `data:` object. Payloads differ by type (backend/dap/agent/loop.py). */
export interface RunEvent {
  seq: number;
  attempt: number;
  type: EventType;
  payload: Record<string, unknown>;
  created_at: string;
}

export function isTerminal(status: unknown): status is RunStatus {
  return TERMINAL_STATUSES.includes(status as RunStatus);
}
