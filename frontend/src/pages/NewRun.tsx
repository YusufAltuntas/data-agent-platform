import { useCallback, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMe, useServices } from "../context";
import { canStartRun } from "../roles";
import { toError, useLoad } from "../useLoad";

const MAX_QUESTION_CHARS = 2000; // RunIn.question in backend/dap/api/schemas.py

export function NewRun() {
  const { team = "" } = useParams();
  const { api } = useServices();
  const me = useMe();
  const navigate = useNavigate();
  const load = useCallback(() => api.datasets(team), [api, team]);
  const datasets = useLoad(load);
  const [dataset, setDataset] = useState("");
  const [question, setQuestion] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>();

  if (!canStartRun(me, team)) {
    return <p>Your role in this team cannot start runs.</p>;
  }

  // Only the team's granted datasets are offered; the API rejects any other with 403.
  const selected = dataset || datasets.data?.[0]?.id || "";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(undefined);
    try {
      const { run_id } = await api.createRun(team, { dataset: selected, question: question.trim() });
      navigate(`/runs/${run_id}`);
    } catch (err) {
      setError(toError(err).message);
      setSubmitting(false);
    }
  }

  return (
    <section>
      <h1>New run</h1>
      <p>
        <Link to={`/teams/${team}/runs`}>Back to runs</Link>
      </p>
      {datasets.error && <p className="error">{datasets.error.message}</p>}
      {datasets.loading && <p>Loading…</p>}
      {datasets.data?.length === 0 && <p>This team has no datasets yet.</p>}
      {datasets.data && datasets.data.length > 0 && (
        <form className="form" onSubmit={submit}>
          <label>
            Dataset
            <select value={selected} onChange={(e) => setDataset(e.target.value)}>
              {datasets.data.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>
          <p className="muted">{datasets.data.find((d) => d.id === selected)?.description}</p>
          <label>
            Question
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              maxLength={MAX_QUESTION_CHARS}
              rows={4}
              required
              placeholder="Which 5 products had the highest revenue last quarter?"
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={submitting || !question.trim()}>
            {submitting ? "Starting…" : "Start run"}
          </button>
        </form>
      )}
    </section>
  );
}
