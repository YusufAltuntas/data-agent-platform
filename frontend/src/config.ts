/** Runtime settings from `/config.js` (K16); nothing here is built into the bundle. */
export interface AppConfig {
  apiBaseUrl: string;
  oidcIssuer: string;
  oidcClientId: string;
  langfuseBaseUrl?: string; // empty or missing: no trace link
}

declare global {
  interface Window {
    __CONFIG__?: AppConfig;
  }
}

export function loadConfig(): AppConfig {
  const config = window.__CONFIG__;
  if (!config?.apiBaseUrl || !config.oidcIssuer || !config.oidcClientId) {
    throw new Error("window.__CONFIG__ is missing; /config.js did not load.");
  }
  return config;
}
