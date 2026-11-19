import { describe, expect, it } from "vitest";
import { addEvent, emptyTimeline } from "./timeline";
import type { RunEvent } from "./types";

function event(seq: number, attempt: number, type: RunEvent["type"] = "llm_call"): RunEvent {
  return { seq, attempt, type, payload: {}, created_at: "2026-11-19T10:00:00+00:00" };
}

describe("timeline reducer", () => {
  it("drops an event whose seq was already seen", () => {
    let timeline = emptyTimeline;
    for (const e of [event(1, 1), event(2, 1), event(2, 1), event(1, 1), event(3, 1)]) {
      timeline = addEvent(timeline, e);
    }
    expect(timeline.attempts).toHaveLength(1);
    expect(timeline.attempts[0]?.events.map((e) => e.seq)).toEqual([1, 2, 3]);
  });

  it("groups events by attempt, in attempt and seq order", () => {
    let timeline = emptyTimeline;
    for (const e of [event(1, 1, "status"), event(2, 1), event(3, 2, "status"), event(4, 2)]) {
      timeline = addEvent(timeline, e);
    }
    expect(timeline.attempts.map((a) => a.attempt)).toEqual([1, 2]);
    expect(timeline.attempts[0]?.events.map((e) => e.seq)).toEqual([1, 2]);
    expect(timeline.attempts[1]?.events.map((e) => e.seq)).toEqual([3, 4]);
  });

  it("returns the same state for a duplicate, so React skips the render", () => {
    const once = addEvent(emptyTimeline, event(1, 1));
    expect(addEvent(once, event(1, 1))).toBe(once);
  });
});
