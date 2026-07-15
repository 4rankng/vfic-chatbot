import { createContext, useContext, type ReactNode } from "react";

import type { CompiledRuntime } from "./types";

const RuntimeCapabilityContext = createContext<CompiledRuntime | null>(null);

export const RuntimeCapabilityProvider = ({
  children,
  runtime,
}: {
  children: ReactNode;
  runtime: CompiledRuntime;
}) => (
  <RuntimeCapabilityContext.Provider value={runtime}>
    {children}
  </RuntimeCapabilityContext.Provider>
);

export const useCompiledRuntime = (): CompiledRuntime => {
  const runtime = useContext(RuntimeCapabilityContext);
  if (!runtime) throw new Error("RuntimeCapabilityProvider is required");
  return runtime;
};
