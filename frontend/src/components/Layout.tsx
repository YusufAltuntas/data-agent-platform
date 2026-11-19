import { Link, Outlet } from "react-router";
import { useMe } from "../context";

export function Layout({ onSignOut }: { onSignOut: () => void }) {
  const me = useMe();
  return (
    <>
      <header className="header">
        <Link to="/" className="brand">
          Data Agent Platform
        </Link>
        <span className="spacer" />
        <span className="muted">{me.email}</span>
        <button type="button" onClick={onSignOut}>
          Sign out
        </button>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </>
  );
}
