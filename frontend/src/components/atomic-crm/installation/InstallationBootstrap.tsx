import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  applyRuntimeMetadata,
  resetRuntimeMetadata,
} from "../root/runtime-metadata";
import { InstallationProvider } from "./InstallationContext";
import type { InstallationContextValue } from "./installation-context";
import {
  fetchRuntimeManifest,
  type PublicRuntimeManifest,
} from "./runtime-manifest";
import { getStaticRecruitmentRuntimeKey } from "../capabilities/static-recruitment-runtime";
import { resetActiveRuntimeState } from "../root/reset-runtime-state";

const LEGACY_CONFIGURATION_KEY = "app.configuration";
const AUTOMATIC_ATTEMPTS = 2;

const DEFAULT_RECRUITMENT_MANIFEST: PublicRuntimeManifest = {
  schema_version: 1,
  lifecycle: "UNCONFIGURED",
  authority_generation: 0,
  revision_id: null,
  pack_key: null,
  pack_version: null,
  pack_contract_hash: null,
  manifest_checksum: null,
  customer_identity: null,
  branding: null,
  locale: null,
  timezone: null,
  currency: null,
  terminology: null,
  capability_ids: [],
  legacy_workspace: false,
  readiness_code: "SETUP_REQUIRED",
};

export const InstallationBootstrap = ({
  children,
}: {
  children: ReactNode;
}) => {
  const [manifest, setManifest] = useState<PublicRuntimeManifest>(
    DEFAULT_RECRUITMENT_MANIFEST,
  );
  const currentManifestRef = useRef<PublicRuntimeManifest | null>(null);
  const inFlightRef = useRef<Promise<void> | null>(null);

  const load = useCallback(async (): Promise<void> => {
    if (inFlightRef.current) return inFlightRef.current;
    const operation = (async () => {
      if (!currentManifestRef.current) {
        resetRuntimeMetadata();
      }

      let lastError: unknown;
      for (let attempt = 0; attempt < AUTOMATIC_ATTEMPTS; attempt += 1) {
        try {
          const manifest = await fetchRuntimeManifest();
          const previous = currentManifestRef.current;
          if (
            previous &&
            getStaticRecruitmentRuntimeKey(previous.authority_generation) !==
              getStaticRecruitmentRuntimeKey(manifest.authority_generation)
          ) {
            await resetActiveRuntimeState();
          }
          currentManifestRef.current = manifest;
          applyRuntimeMetadata(manifest);
          setManifest(manifest);
          return;
        } catch (error) {
          lastError = error;
        }
      }
      void lastError;
      if (!currentManifestRef.current) resetRuntimeMetadata();
    })();
    inFlightRef.current = operation;
    try {
      await operation;
    } finally {
      inFlightRef.current = null;
    }
  }, []);

  useEffect(() => {
    try {
      window.localStorage.removeItem(LEGACY_CONFIGURATION_KEY);
    } catch {
      // Storage can be unavailable in hardened browsers. Runtime authority is
      // still network-only and never reads this legacy key.
    }
    void load();
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") void load();
    };
    window.addEventListener("focus", refreshWhenVisible);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.removeEventListener("focus", refreshWhenVisible);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      resetRuntimeMetadata();
    };
  }, [load]);

  const contextValue = useMemo<InstallationContextValue>(
    () => ({ manifest, refreshRuntime: load }),
    [load, manifest],
  );

  return (
    <InstallationProvider value={contextValue}>{children}</InstallationProvider>
  );
};
