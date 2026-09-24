import type { ReactNode } from "react";

import { RuntimeCapabilityContext } from "./runtime-context";
import type { CompiledRuntime } from "./types";

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
