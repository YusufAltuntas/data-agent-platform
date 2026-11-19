import { useCallback, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { StatusBadge } from "../components/StatusBadge";
import { useMe, useServices } from "../context";
import { formatCost, formatTime } from "../format";
import { canManageTeam } from "../roles";
import type { Role } from "../types";
import { toError, useLoad } from "../useLoad";

const ROLES: Role[] = ["viewer", "analyst", "admin"];

export function TeamAdmin() {
  const { team = "" } = useParams();
  const me = useMe();
  if (!canManageTeam(me, team)) {
    return <p>Only team admins can manage members and see the budget.</p>;
  }
  return (
    <section>
      <p>
        <Link to={`/teams/${team}/runs`}>Back to runs</Link>
      </p>
      <h1>Team admin: {team}</h1>
      <Members team={team} />
      <BudgetView team={team} />
    </section>
  );
}

/** The API has no member list: members are added, changed and removed by e-mail. */
function Members({ team }: { team: string }) {
  const { api } = useServices();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; error?: boolean }>();

  async function act(change: () => Promise<string>) {
    setBusy(true);
    try {
      setMessage({ text: await change() });
    } catch (err) {
      setMessage({ text: toError(err).message, error: true });
    } finally {
      setBusy(false);
    }
  }

  function save(e: FormEvent) {
    e.preventDefault();
    void act(async () => {
      const member = await api.putMember(team, email.trim(), role);
      return `${member.email} is now ${member.role}.`;
    });
  }

  function remove() {
    void act(async () => {
      await api.deleteMember(team, email.trim());
      return `${email.trim()} was removed from the team.`;
    });
  }

  return (
    <>
      <h2>Members</h2>
      <p className="muted">Enter an e-mail to add a member, change their role or remove them.</p>
      <form className="form inline" onSubmit={save}>
        <label>
          E-mail
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Role
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" disabled={busy}>
          Add or update
        </button>
        <button type="button" className="danger" onClick={remove} disabled={busy || !email.trim()}>
          Remove
        </button>
      </form>
      {message && <p className={message.error ? "error" : "muted"}>{message.text}</p>}
    </>
  );
}

function BudgetView({ team }: { team: string }) {
  const { api } = useServices();
  const load = useCallback(() => api.budget(team), [api, team]);
  const { data, error, loading } = useLoad(load);

  return (
    <>
      <h2>Budget</h2>
      {error && <p className="error">{error.message}</p>}
      {loading && <p>Loading…</p>}
      {data && (
        <>
          {data.max_budget_usd == null && data.spend_usd == null ? (
            <p className="muted">No LLM budget is set up for this team yet.</p>
          ) : (
            <p>
              Spent <strong>{formatCost(data.spend_usd)}</strong> of{" "}
              <strong>{data.max_budget_usd == null ? "no limit" : formatCost(data.max_budget_usd)}</strong>
            </p>
          )}
          <table>
            <thead>
              <tr>
                <th>Created</th>
                <th>By</th>
                <th>Status</th>
                <th>Tokens</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.runs.map((run) => (
                <tr key={run.id}>
                  <td>
                    <Link to={`/runs/${run.id}`}>{formatTime(run.created_at)}</Link>
                  </td>
                  <td>{run.created_by}</td>
                  <td>
                    <StatusBadge status={run.status} />
                  </td>
                  <td>{(run.prompt_tokens ?? 0) + (run.completion_tokens ?? 0)}</td>
                  <td>{formatCost(run.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}
