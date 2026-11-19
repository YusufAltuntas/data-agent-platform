import { useCallback } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { MeContext, useMe, useServices } from "./context";
import { NewRun } from "./pages/NewRun";
import { RunDetailPage } from "./pages/RunDetail";
import { RunList } from "./pages/RunList";
import { TeamAdmin } from "./pages/TeamAdmin";
import { useLoad } from "./useLoad";

export function App({ onSignOut }: { onSignOut: () => void }) {
  const { api } = useServices();
  const load = useCallback(() => api.me(), [api]);
  const me = useLoad(load);

  if (me.error) return <p className="error page">{me.error.message}</p>;
  if (!me.data) return <p className="page">Loading…</p>;

  return (
    <MeContext value={me.data}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout onSignOut={onSignOut} />}>
            <Route index element={<Home />} />
            <Route path="teams/:team/runs" element={<RunList />} />
            <Route path="teams/:team/runs/new" element={<NewRun />} />
            <Route path="teams/:team/admin" element={<TeamAdmin />} />
            <Route path="runs/:runId" element={<RunDetailPage />} />
            <Route path="*" element={<p>Page not found.</p>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </MeContext>
  );
}

function Home() {
  const me = useMe();
  const first = me.teams[0];
  if (!first) {
    return <p>You are not a member of any team.</p>;
  }
  return <Navigate to={`/teams/${first.id}/runs`} replace />;
}
