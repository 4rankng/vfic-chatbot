import { createContext, useContext } from "react";

import type { CompiledRuntime } from "./types";

/**
 * Backs {@link RuntimeCapabilityProvider}. The provider lives in its own
 * component module so this file stays component-free — a file exporting both a
 * component and a hook disables Fast Refresh (react-refresh/only-export-components).
 */
export const RuntimeCapabilityContext = createContext<CompiledRuntime | null>(
  null,
);

export const useCompiledRuntime = (): CompiledRuntime => {
  const runtime = useContext(RuntimeCapabilityContext);
  if (!runtime) throw new Error("RuntimeCapabilityProvider is required");
  return runtime;
};
