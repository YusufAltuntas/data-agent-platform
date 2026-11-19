import type { User, UserManager } from "oidc-client-ts";
import { useEffect, useState, type ReactNode } from "react";
import { redirectToSignIn, signIn } from "./auth";
import { toError } from "./useLoad";

/** Renders its children only for a signed-in user. */
export function AuthGate({ userManager, children }: { userManager: UserManager; children: ReactNode }) {
  const [user, setUser] = useState<User>();
  const [error, setError] = useState<Error>();

  useEffect(() => {
    let active = true;
    signIn(userManager).then(
      (signedIn) => {
        if (active && signedIn) setUser(signedIn);
      },
      (err: unknown) => {
        if (active) setError(toError(err));
      },
    );
    // The library renews the token in the background; if that fails, sign in again.
    const expired = () => void redirectToSignIn(userManager);
    userManager.events.addAccessTokenExpired(expired);
    return () => {
      active = false;
      userManager.events.removeAccessTokenExpired(expired);
    };
  }, [userManager]);

  if (error) {
    return <p className="error page">Sign-in failed: {error.message}</p>;
  }
  return user ? children : <p className="page">Signing in…</p>;
}
