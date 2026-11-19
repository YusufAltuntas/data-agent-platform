import { fetchEventSource } from "@microsoft/fetch-event-source";
import {
  isTerminal,
  type Budget,
  type Dataset,
  type Me,
  type Member,
  type Role,
  type RunDetail,
  type RunEvent,
  type RunPage,
} from "./types";

/** A non-2xx API response. `code` is set for structured errors such as `budget_exceeded`. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | undefined;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export interface Api {
  me(): Promise<Me>;
  datasets(team: string): Promise<Dataset[]>;
  listRuns(team: string, cursor?: string): Promise<RunPage>;
  createRun(team: string, body: { dataset: string; question: string }): Promise<{ run_id: string }>;
  getRun(runId: string): Promise<RunDetail>;
  cancelRun(runId: string): Promise<void>;
  budget(team: string): Promise<Budget>;
  putMember(team: string, email: string, role: Role): Promise<Member>;
  deleteMember(team: string, email: string): Promise<void>;
  /**
   * Follow the run's events (K12, K13) until a final status arrives or `signal` aborts.
   * The library reconnects on network errors and sends `Last-Event-ID`.
   */
  streamEvents(runId: string, onEvent: (event: RunEvent) => void, signal: AbortSignal): Promise<void>;
}

export interface ApiOptions {
  baseUrl: string;
  getToken: () => Promise<string | null>;
  fetch?: typeof fetch;
}

export function createApi({ baseUrl, getToken, fetch: fetchFn }: ApiOptions): Api {
  const doFetch = fetchFn ?? ((input, init) => window.fetch(input, init));

  /** Every request carries the current access token; it is read per request, so renewals apply. */
  async function authorizedFetch(url: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    const token = await getToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    return doFetch(url, { ...init, headers });
  }

  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await authorizedFetch(baseUrl + path, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      throw await errorFrom(response);
    }
    return (response.status === 204 ? undefined : await response.json()) as T;
  }

  /** Whether the run is final; a network failure counts as "not yet" so the caller reconnects. */
  async function runFinished(runId: string): Promise<boolean> {
    try {
      return isTerminal((await request<RunDetail>("GET", run(runId))).status);
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      return false;
    }
  }

  const team = (id: string) => `/teams/${encodeURIComponent(id)}`;
  const run = (id: string) => `/runs/${encodeURIComponent(id)}`;
  const member = (teamId: string, email: string) =>
    `${team(teamId)}/members/${encodeURIComponent(email)}`;

  return {
    me: () => request("GET", "/me"),
    datasets: (id) => request("GET", `${team(id)}/datasets`),
    listRuns: (id, cursor) =>
      request("GET", `${team(id)}/runs${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`),
    createRun: (id, body) => request("POST", `${team(id)}/runs`, body),
    getRun: (id) => request("GET", run(id)),
    cancelRun: (id) => request("POST", `${run(id)}/cancel`),
    budget: (id) => request("GET", `${team(id)}/budget`),
    putMember: (id, email, role) => request("PUT", member(id, email), { role }),
    deleteMember: (id, email) => request("DELETE", member(id, email)),

    async streamEvents(runId, onEvent, signal) {
      let lastSeq = 0;
      for (;;) {
        let finished = false;
        await fetchEventSource(`${baseUrl}${run(runId)}/events`, {
          signal,
          // The library's own (lowercase) key, so the ids it records overwrite this one.
          headers: lastSeq ? { "last-event-id": String(lastSeq) } : {},
          openWhenHidden: true, // keep one connection instead of reconnecting on tab switches
          fetch: (input, init) => authorizedFetch(String(input), init),
          async onopen(response) {
            if (!response.ok) {
              throw await errorFrom(response);
            }
          },
          onmessage(message) {
            if (!message.data) {
              return;
            }
            const event = JSON.parse(message.data) as RunEvent;
            lastSeq = Math.max(lastSeq, event.seq);
            onEvent(event);
            if (event.type === "status" && isTerminal(event.payload["status"])) {
              finished = true;
            }
          },
          onerror(error) {
            if (error instanceof ApiError) {
              throw error; // the API refused the stream: do not retry
            }
            // returning nothing retries after the library's default interval
          },
        });
        if (finished || signal.aborted) {
          return;
        }
        // The server also ends the stream when the run row is final without a final status
        // event (e.g. a run that could not be queued); only an unfinished run reconnects.
        if (await runFinished(runId)) {
          return;
        }
        await delay(RECONNECT_DELAY_MS, signal);
        if (signal.aborted) {
          return;
        }
      }
    },
  };
}

const RECONNECT_DELAY_MS = 1000;

function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

async function errorFrom(response: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail;
  } catch {
    detail = undefined;
  }
  if (typeof detail === "string") {
    return new ApiError(response.status, detail);
  }
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc, msg, type}, ...]
    const messages = detail.map((d: { msg?: string }) => d.msg ?? "").filter(Boolean);
    return new ApiError(response.status, messages.join("; ") || "Invalid request");
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    const { code, message } = detail as { code?: string; message: string };
    return new ApiError(response.status, message, code);
  }
  return new ApiError(response.status, `Request failed (${response.status})`);
}
