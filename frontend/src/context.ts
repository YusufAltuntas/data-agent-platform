import { createContext, useContext } from "react";
import type { Api } from "./api";
import type { AppConfig } from "./config";
import type { Me } from "./types";

export interface Services {
  api: Api;
  config: AppConfig;
}

export const ServicesContext = createContext<Services | null>(null);
export const MeContext = createContext<Me | null>(null);

export function useServices(): Services {
  const services = useContext(ServicesContext);
  if (!services) {
    throw new Error("useServices outside ServicesContext");
  }
  return services;
}

/** The signed-in user from `GET /api/me`. */
export function useMe(): Me {
  const me = useContext(MeContext);
  if (!me) {
    throw new Error("useMe outside MeContext");
  }
  return me;
}
