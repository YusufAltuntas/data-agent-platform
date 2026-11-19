import { formatCost } from "../format";
import type { Timeline } from "../timeline";
import type { RunEvent } from "../types";

export function TimelineView({ timeline }: { timeline: Timeline }) {
  if (timeline.attempts.length === 0) {
    return <p className="muted">Waiting for events…</p>;
  }
  return (
    <div className="timeline">
      {timeline.attempts.map(({ attempt, events }) => (
        <section key={attempt} className="attempt">
          <h3>Attempt {attempt}</h3>
          <ol>
            {events.map((event) => (
              <li key={event.seq} className={`event event-${event.type}`}>
                <EventItem event={event} />
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}

// Payload shapes: backend/dap/agent/loop.py (and `status` from the worker: {status, ...}).
function EventItem({ event }: { event: RunEvent }) {
  const p = event.payload;
  const time = new Date(event.created_at).toLocaleTimeString();
  const head = (title: string) => (
    <div className="event-head">
      <strong>{title}</strong> <span className="muted">{time}</span>
    </div>
  );

  switch (event.type) {
    case "status":
      return head(`Status: ${String(p["status"])}`);
    case "llm_call":
      return (
        <>
          {head(`Model call (step ${String(p["step"])})`)}
          <span className="muted">
            {String(p["prompt_tokens"])} prompt + {String(p["completion_tokens"])} completion tokens,{" "}
            {formatCost(p["cost_usd"] as number | null)}
          </span>
          {typeof p["text"] === "string" && p["text"] && <p>{p["text"]}</p>}
        </>
      );
    case "tool_call":
      return (
        <>
          {head(`Tool call: ${String(p["name"])}`)}
          <pre>{prettyArguments(p["arguments"])}</pre>
        </>
      );
    case "tool_result":
      return (
        <>
          {head(`${p["ok"] ? "Result" : "Failed"}: ${String(p["name"])}`)}
          <pre>{summarize(p["data"])}</pre>
        </>
      );
    case "answer":
      return (
        <>
          {head("Answer")}
          <p>{String(p["answer"])}</p>
        </>
      );
    case "error":
      return (
        <>
          {head(`Error: ${String(p["code"])}`)}
          <p className="error">{String(p["message"])}</p>
        </>
      );
    default:
      return head(event.type);
  }
}

/** Tool arguments are a JSON string; show `sql` as-is, anything else pretty-printed. */
function prettyArguments(raw: unknown): string {
  try {
    const args = JSON.parse(String(raw)) as Record<string, unknown>;
    return typeof args["sql"] === "string" ? args["sql"] : JSON.stringify(args, null, 2);
  } catch {
    return String(raw);
  }
}

function summarize(data: unknown): string {
  const d = (data ?? {}) as Record<string, unknown>;
  if (typeof d["error"] === "string") return d["error"];
  if (Array.isArray(d["tables"])) return `Tables: ${d["tables"].join(", ")}`;
  if (Array.isArray(d["columns"]) && Array.isArray(d["rows"])) {
    const more = d["truncated"] ? " (truncated)" : "";
    return `${d["rows"].length} rows${more}; columns: ${d["columns"].join(", ")}`;
  }
  if (Array.isArray(d["columns"])) {
    const columns = d["columns"] as { name: string; type: string }[];
    return `${String(d["table"])}: ${columns.map((c) => `${c.name} ${c.type}`).join(", ")}`;
  }
  return JSON.stringify(d, null, 2);
}
