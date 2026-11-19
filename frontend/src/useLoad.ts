import { useEffect, useState } from "react";

export interface Loaded<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
}

/**
 * Run `load` and keep its result. Pass a stable function (`useCallback`); a new function
 * loads again, and results of an older one are ignored.
 */
export function useLoad<T>(load: () => Promise<T>): Loaded<T> {
  const [state, setState] = useState<{ load?: () => Promise<T>; data?: T; error?: Error }>({});

  useEffect(() => {
    let active = true;
    load().then(
      (data) => {
        if (active) setState({ load, data });
      },
      (error: unknown) => {
        if (active) setState({ load, error: toError(error) });
      },
    );
    return () => {
      active = false;
    };
  }, [load]);

  const current = state.load === load;
  return {
    data: current ? state.data : undefined,
    error: current ? state.error : undefined,
    loading: !current,
  };
}

export function toError(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error));
}
