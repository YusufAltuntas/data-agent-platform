import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createApi } from "./api";
import { App } from "./App";
import { createUserManager } from "./auth";
import { AuthGate } from "./AuthGate";
import { loadConfig } from "./config";
import { ServicesContext } from "./context";
import "./styles.css";

const root = createRoot(document.getElementById("root") as HTMLElement);

try {
  const config = loadConfig();
  const userManager = createUserManager(config);
  const api = createApi({
    baseUrl: config.apiBaseUrl,
    getToken: async () => (await userManager.getUser())?.access_token ?? null,
  });
  root.render(
    <StrictMode>
      <ServicesContext value={{ api, config }}>
        <AuthGate userManager={userManager}>
          <App onSignOut={() => void userManager.signoutRedirect()} />
        </AuthGate>
      </ServicesContext>
    </StrictMode>,
  );
} catch (error) {
  root.render(<p className="error page">{String(error)}</p>);
}
