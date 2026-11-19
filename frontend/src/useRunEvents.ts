import { useEffect, useReducer, useState } from "react";
import { useServices } from "./context";
import { addEvent, emptyTimeline, type Timeline } from "./timeline";
import { toError } from "./useLoad";

/**
 * The run's live timeline over SSE (K12, K13). `onFinished` is called once the stream has
 * delivered the final status. Mount once per run (key the component by run id).
 */
export function useRunEvents(runId: string, onFinished: () => void): { timeline: Timeline; error?: Error } {
  const { api } = useServices();
  const [timeline, dispatch] = useReducer(addEvent, emptyTimeline);
  const [error, setError] = useState<Error>();

  useEffect(() => {
    const controller = new AbortController();
    api.streamEvents(runId, dispatch, controller.signal).then(
      () => {
        if (!controller.signal.aborted) onFinished();
      },
      (err: unknown) => {
        if (!controller.signal.aborted) setError(toError(err));
      },
    );
    return () => controller.abort();
  }, [api, runId, onFinished]);

  return { timeline, error };
}
