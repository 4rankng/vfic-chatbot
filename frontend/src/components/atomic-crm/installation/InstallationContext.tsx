import type { ReactNode } from "react";

import {
  InstallationContext,
  type InstallationContextValue,
} from "./installation-context";

export const InstallationProvider = ({
  children,
  value,
}: {
  children: ReactNode;
  value: InstallationContextValue;
}) => (
  <InstallationContext.Provider value={value}>
    {children}
  </InstallationContext.Provider>
);
