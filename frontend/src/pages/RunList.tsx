import { useCallback } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { StatusBadge } from "../components/StatusBadge";
import { useMe, useServices } from "../context";
import { formatCost, formatTime } from "../format";
import { canManageTeam, canStartRun } from "../roles";
import { useLoad } from "../useLoad";

export function RunList() {
  const { team = "" } = useParams();
  const [params] = useSearchParams();
  const cursor = params.get("cursor") ?? undefined;
  const { api } = useServices();
  const me = useMe();
  const navigate = useNavigate();
  const load = useCallback(() => api.listRuns(team, cursor), [api, team, cursor]);
  const { data, error, loading } = useLoad(load);

  // A platform admin may open a team they are not a member of.
  const teams = me.teams.some((t) => t.id === team) ? me.teams : [{ id: team, name: team }, ...me.teams];

  return (
    <section>
      <div className="toolbar">
        <h1>Runs</h1>
        <label>
          Team{" "}
          <select value={team} onChange={(e) => navigate(`/teams/${e.target.value}/runs`)}>
            {teams.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <span className="spacer" />
        {canManageTeam(me, team) && <Link to={`/teams/${team}/admin`}>Team admin</Link>}
        {canStartRun(me, team) && (
          <Link className="button" to={`/teams/${team}/runs/new`}>
            New run
          </Link>
        )}
      </div>

      {error && <p className="error">{error.message}</p>}
      {loading && <p>Loading…</p>}
      {data && data.items.length === 0 && <p>No runs yet.</p>}
      {data && data.items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Created</th>
              <th>Question</th>
              <th>Dataset</th>
              <th>By</th>
              <th>Status</th>
              <th>Cost</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((run) => (
              <tr key={run.id}>
                <td>{formatTime(run.created_at)}</td>
                <td>
                  <Link to={`/runs/${run.id}`}>{run.question}</Link>
                </td>
                <td>{run.dataset_id}</td>
                <td>{run.created_by}</td>
                <td>
                  <StatusBadge status={run.status} />
                </td>
                <td>{formatCost(run.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <nav className="pager">
        {cursor && <Link to={`/teams/${team}/runs`}>Newest</Link>}
        {data?.next_cursor && (
          <Link to={`/teams/${team}/runs?cursor=${encodeURIComponent(data.next_cursor)}`}>Older</Link>
        )}
      </nav>
    </section>
  );
}
