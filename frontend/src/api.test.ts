import { describe, expect, it, vi } from "vitest";
import { ApiError, createApi } from "./api";
import type { RunEvent } from "./types";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function authHeader(call: unknown[] | undefined): string | null {
  const init = call?.[1] as RequestInit;
  return new Headers(init.headers).get("Authorization");
}

describe("API client", () => {
  it("sends the access token as a Bearer Authorization header", async () => {
    const fetch = vi.fn().mockResolvedValue(json({ email: "a@x", platform_admin: false, teams: [] }));
    const api = createApi({ baseUrl: "/api", getToken: async () => "tok-1", fetch });

    const me = await api.me();

    expect(me.email).toBe("a@x");
    expect(fetch.mock.calls[0]?.[0]).toBe("/api/me");
    expect(authHeader(fetch.mock.calls[0])).toBe("Bearer tok-1");
  });

  it("turns an error body into an ApiError with the detail message", async () => {
    const detail = { code: "budget_exceeded", message: "The team's LLM budget is used up" };
    const fetch = vi.fn().mockResolvedValue(json({ detail }, 402));
    const api = createApi({ baseUrl: "/api", getToken: async () => "tok", fetch });

    const error = await api.createRun("sales", { dataset: "sales", question: "q" }).catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(402);
    expect(error.code).toBe("budget_exceeded");
    expect(error.message).toBe("The team's LLM budget is used up");
  });

  it("opens the event stream with the Authorization header and stops at a final status", async () => {
    const events: RunEvent[] = [
      { seq: 1, attempt: 1, type: "status", payload: { status: "running" }, created_at: "t" },
      { seq: 2, attempt: 1, type: "status", payload: { status: "succeeded" }, created_at: "t" },
    ];
    const body = events.map((e) => `id: ${e.seq}\ndata: ${JSON.stringify(e)}\n\n`).join("");
    const fetch = vi.fn().mockResolvedValue(
      new Response(body, { headers: { "Content-Type": "text/event-stream" } }),
    );
    const api = createApi({ baseUrl: "/api", getToken: async () => "tok-2", fetch });
    const received: RunEvent[] = [];

    await api.streamEvents("run-1", (e) => received.push(e), new AbortController().signal);

    expect(fetch.mock.calls[0]?.[0]).toBe("/api/runs/run-1/events");
    expect(authHeader(fetch.mock.calls[0])).toBe("Bearer tok-2");
    expect(received.map((e) => e.seq)).toEqual([1, 2]);
  });

  function sse(events: RunEvent[]): Response {
    const body = events.map((e) => `id: ${e.seq}\ndata: ${JSON.stringify(e)}\n\n`).join("");
    return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
  }

  it("stops when the stream closes without a final status but the run has finished", async () => {
    const fetch = vi.fn(async (url: string) =>
      url.endsWith("/events") ? sse([]) : json({ id: "run-1", status: "failed" }),
    );
    const api = createApi({ baseUrl: "/api", getToken: async () => "tok", fetch: fetch as typeof window.fetch });

    await api.streamEvents("run-1", () => undefined, new AbortController().signal);

    expect(fetch.mock.calls.map((c) => c[0])).toEqual(["/api/runs/run-1/events", "/api/runs/run-1"]);
  });

  it("reconnects after the last seq when the stream closes before the run has finished", async () => {
    const running: RunEvent = { seq: 1, attempt: 1, type: "status", payload: { status: "running" }, created_at: "t" };
    const done: RunEvent = { seq: 2, attempt: 1, type: "status", payload: { status: "succeeded" }, created_at: "t" };
    const streams = [sse([running]), sse([done])];
    const fetch = vi.fn(async (url: string) =>
      url.endsWith("/events") ? (streams.shift() as Response) : json({ id: "run-1", status: "running" }),
    );
    const api = createApi({ baseUrl: "/api", getToken: async () => "tok", fetch: fetch as typeof window.fetch });
    const received: RunEvent[] = [];

    await api.streamEvents("run-1", (e) => received.push(e), new AbortController().signal);

    expect(received.map((e) => e.seq)).toEqual([1, 2]);
    expect(fetch.mock.calls.map((c) => c[0])).toEqual([
      "/api/runs/run-1/events",
      "/api/runs/run-1",
      "/api/runs/run-1/events",
    ]);
    const reconnect = (fetch.mock.calls[2] as unknown[])[1] as RequestInit;
    expect(new Headers(reconnect.headers).get("Last-Event-ID")).toBe("1");
  });

  it("sends one Last-Event-ID, the latest seq, when retrying after a reconnect", async () => {
    const event = (seq: number, status: string): RunEvent => ({
      seq,
      attempt: 1,
      type: "status",
      payload: { status },
      created_at: "t",
    });
    // The second stream delivers seq 2, then the connection drops (the library retries).
    let pulls = 0;
    const dropping = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (pulls++ === 0) {
          const e = event(2, "running");
          controller.enqueue(new TextEncoder().encode(`id: 2\ndata: ${JSON.stringify(e)}\n\n`));
        } else {
          controller.error(new TypeError("network error"));
        }
      },
    });
    const streams = [
      sse([event(1, "running")]),
      new Response(dropping, { headers: { "Content-Type": "text/event-stream" } }),
      sse([event(3, "succeeded")]),
    ];
    const fetch = vi.fn(async (url: string) =>
      url.endsWith("/events") ? (streams.shift() as Response) : json({ id: "run-1", status: "running" }),
    );
    const api = createApi({ baseUrl: "/api", getToken: async () => "tok", fetch: fetch as typeof window.fetch });
    const received: RunEvent[] = [];

    await api.streamEvents("run-1", (e) => received.push(e), new AbortController().signal);

    expect(received.map((e) => e.seq)).toEqual([1, 2, 3]);
    const retry = (fetch.mock.calls[3] as unknown[])[1] as RequestInit;
    expect(fetch.mock.calls[3]?.[0]).toBe("/api/runs/run-1/events");
    expect(new Headers(retry.headers).get("Last-Event-ID")).toBe("2");
  });

  it("reconnects when the run check fails with a network error", async () => {
    const done: RunEvent = { seq: 1, attempt: 1, type: "status", payload: { status: "succeeded" }, created_at: "t" };
    const streams = [sse([]), sse([done])];
    const fetch = vi.fn(async (url: string) => {
      if (url.endsWith("/events")) return streams.shift() as Response;
      throw new TypeError("Failed to fetch");
    });
    const api = createApi({ baseUrl: "/api", getToken: async () => "tok", fetch: fetch as typeof window.fetch });

    await api.streamEvents("run-1", () => undefined, new AbortController().signal);

    expect(fetch.mock.calls.map((c) => c[0])).toEqual([
      "/api/runs/run-1/events",
      "/api/runs/run-1",
      "/api/runs/run-1/events",
    ]);
  });
});
