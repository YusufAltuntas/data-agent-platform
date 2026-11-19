import type { RunEvent } from "./types";

/** One run of the agent; a run restarted by the worker gets a second attempt (K12). */
export interface Attempt {
  attempt: number;
  events: RunEvent[]; // in seq order
}

export interface Timeline {
  seen: ReadonlySet<number>;
  attempts: Attempt[]; // in attempt order
}

export const emptyTimeline: Timeline = { seen: new Set(), attempts: [] };

/**
 * Add an event to the timeline. An event whose `seq` was already seen (sent again after a
 * reconnect) is dropped and the same state is returned.
 */
export function addEvent(timeline: Timeline, event: RunEvent): Timeline {
  if (timeline.seen.has(event.seq)) {
    return timeline;
  }
  const seen = new Set(timeline.seen).add(event.seq);
  const current = timeline.attempts.find((a) => a.attempt === event.attempt);
  const events = [...(current?.events ?? []), event].sort((a, b) => a.seq - b.seq);
  const attempts = [
    ...timeline.attempts.filter((a) => a.attempt !== event.attempt),
    { attempt: event.attempt, events },
  ].sort((a, b) => a.attempt - b.attempt);
  return { seen, attempts };
}
