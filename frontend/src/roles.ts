// What the UI offers, mirroring backend/dap/authz.py (design §6). The API still decides.
import type { Me, Role, RunSummary } from "./types";

export function roleIn(me: Me, team: string): Role | undefined {
  return me.teams.find((t) => t.id === team)?.role;
}

function isAdmin(me: Me, team: string): boolean {
  return me.platform_admin || roleIn(me, team) === "admin";
}

export function canStartRun(me: Me, team: string): boolean {
  return isAdmin(me, team) || roleIn(me, team) === "analyst";
}

export function canCancelRun(me: Me, run: RunSummary): boolean {
  if (isAdmin(me, run.team_id)) {
    return true;
  }
  return roleIn(me, run.team_id) === "analyst" && run.created_by === me.email;
}

/** Team admin page: members and budget. */
export function canManageTeam(me: Me, team: string): boolean {
  return isAdmin(me, team);
}
