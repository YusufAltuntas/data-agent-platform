import { useCallback, useState } from "react";
import { Link, useParams } from "react-router";
import { AnswerView } from "../components/AnswerView";
import { StatusBadge } from "../components/StatusBadge";
import { TimelineView } from "../components/TimelineView";
import { useMe, useServices } from "../context";
import { formatCost, formatTime } from "../format";
import { canCancelRun } from "../roles";
import { isTerminal, type RunDetail as Run } from "../types";
import { toError, useLoad } from "../useLoad";
import { useRunEvents } from "../useRunEvents";

export function RunDetailPage() {
  const { runId = "" } = useParams();
  return <RunView key={runId} runId={runId} />; // a new run starts with a fresh timeline
}

function RunView({ runId }: { runId: string }) {
  const { api, config } = useServices();
  const me = useMe();
  const load = useCallback(() => api.getRun(runId), [api, runId]);
  const loaded = useLoad(load);
  const [final, setFinal] = useState<Run>();
  const [cancel, setCancel] = useState<string>();
  const [cancelError, setCancelError] = useState<string>();

  // The answer, cost and trace id are on the run row: read it again once the run has finished.
  const refresh = useCallback(() => {
    api.getRun(runId).then(setFinal, () => undefined);
  }, [api, runId]);
  const { timeline, error: streamError } = useRunEvents(runId, refresh);

  const run = final ?? loaded.data;
  if (loaded.error) return <p className="error">{loaded.error.message}</p>;
  if (!run) return <p>Loading…</p>;

  const lastStatus = timeline.attempts
    .flatMap((a) => a.events)
    .filter((e) => e.type === "status")
    .at(-1)?.payload["status"];
  const status = final?.status ?? (typeof lastStatus === "string" ? lastStatus : run.status);
  const langfuse = config.langfuseBaseUrl?.replace(/\/$/, "");

  async function requestCancel() {
    setCancel("Cancelling…");
    setCancelError(undefined);
    try {
      await api.cancelRun(runId);
      setCancel("Cancel requested; the run stops after its current step.");
    } catch (err) {
      setCancel(undefined); // let the user try again
      setCancelError(toError(err).message);
    }
  }

  return (
    <section>
      <p>
        <Link to={`/teams/${run.team_id}/runs`}>Back to runs</Link>
      </p>
      <div className="toolbar">
        <h1>{run.question}</h1>
        <span className="spacer" />
        <StatusBadge status={status} />
        {!isTerminal(status) && canCancelRun(me, run) && (
          <button type="button" onClick={requestCancel} disabled={cancel !== undefined}>
            Cancel run
          </button>
        )}
      </div>
      {cancel && <p className="muted">{cancel}</p>}
      {cancelError && <p className="error">{cancelError}</p>}

      <dl className="facts">
        <dt>Dataset</dt>
        <dd>{run.dataset_id}</dd>
        <dt>Started by</dt>
        <dd>{run.created_by}</dd>
        <dt>Created</dt>
        <dd>{formatTime(run.created_at)}</dd>
        <dt>Attempts</dt>
        <dd>{run.attempts}</dd>
        <dt>Cost</dt>
        <dd>{formatCost(run.cost_usd)}</dd>
        <dt>Tokens</dt>
        <dd>
          {run.prompt_tokens ?? "–"} prompt / {run.completion_tokens ?? "–"} completion
        </dd>
        <dt>Model</dt>
        <dd>{run.model ?? "–"}</dd>
        {langfuse && run.trace_id && (
          <>
            <dt>Trace</dt>
            <dd>
              <a href={`${langfuse}/trace/${encodeURIComponent(run.trace_id)}`} target="_blank" rel="noreferrer">
                Open in Langfuse
              </a>
            </dd>
          </>
        )}
      </dl>

      {run.error && <p className="error">Error: {run.error}</p>}
      {run.answer && (
        <>
          <h2>Answer</h2>
          <AnswerView answer={run.answer} />
        </>
      )}

      <h2>Timeline</h2>
      {streamError && <p className="error">Live updates stopped: {streamError.message}</p>}
      <TimelineView timeline={timeline} />
    </section>
  );
}
