import { createContext, useContext } from "react";

import type { PublicRuntimeManifest } from "./runtime-manifest";

export type InstallationContextValue = {
  manifest: PublicRuntimeManifest;
  refreshRuntime: () => Promise<void>;
};

export const InstallationContext =
  createContext<InstallationContextValue | null>(null);

export const useInstallationContext = (): InstallationContextValue => {
  const value = useContext(InstallationContext);
  if (value === null) {
    throw new Error("InstallationProvider is required");
  }
  return value;
};

export const hasReadyActiveRuntime = (
  manifest: PublicRuntimeManifest,
): boolean =>
  manifest.lifecycle === "ACTIVE" && manifest.readiness_code === "READY";
