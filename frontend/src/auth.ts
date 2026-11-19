// OIDC sign-in: Authorization Code + PKCE against Keycloak (public client, no secret).
import { UserManager, type User } from "oidc-client-ts";
import type { AppConfig } from "./config";

export const CALLBACK_PATH = "/callback";

export function createUserManager(config: AppConfig): UserManager {
  const origin = window.location.origin;
  return new UserManager({
    authority: config.oidcIssuer,
    client_id: config.oidcClientId,
    redirect_uri: origin + CALLBACK_PATH,
    post_logout_redirect_uri: origin + "/",
    scope: "openid profile email",
  });
}

let pending: Promise<User | null> | undefined;

/**
 * The signed-in user. On the callback route it completes the code exchange and restores the
 * page the user started from; without a valid session it redirects to Keycloak and resolves
 * to null. Shared across calls, so React's double effects do not redeem the code twice.
 */
export function signIn(userManager: UserManager): Promise<User | null> {
  pending ??= doSignIn(userManager);
  return pending;
}

async function doSignIn(userManager: UserManager): Promise<User | null> {
  if (window.location.pathname === CALLBACK_PATH) {
    const user = await userManager.signinRedirectCallback();
    const returnTo = typeof user.state === "string" ? user.state : "/";
    window.history.replaceState(null, "", returnTo);
    return user;
  }
  const user = await userManager.getUser();
  if (user && !user.expired) {
    return user;
  }
  await redirectToSignIn(userManager);
  return null; // the browser is leaving for Keycloak
}

export function redirectToSignIn(userManager: UserManager): Promise<void> {
  return userManager.signinRedirect({ state: window.location.pathname + window.location.search });
}
