import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import { useNotify } from "ra-core";

import {
  zaloIntegrationGateway,
  type CustomLlmSettings,
  type JevSettings,
  type MinimaxSettings,
  type OpenRouterSettings,
  type ZaloSettings,
} from "../api";
import type { SettingsStatusState } from "../SettingsFieldStatus";
import type { ProviderSettingsBundle } from "../domain/providerDescriptors";

/**
 * One query key per settings endpoint, mirroring the Facebook integration's
 * `["facebook-credentials"]` convention so a save can write back exactly the
 * resource it changed.
 */
export const integrationSettingsKeys = {
  zalo: ["zalo-settings"],
  minimax: ["minimax-settings"],
  openRouter: ["openrouter-settings"],
  customLlm: ["custom-llm-settings"],
  jev: ["jev-settings"],
} as const;

const SETTINGS_STALE_TIME = 30_000;

export type SettingsBundle = {
  zalo: ZaloSettings | null;
  providers: ProviderSettingsBundle;
  statusState: SettingsStatusState;
};

/**
 * Owns the settings load: five endpoints fetched in parallel, one shared
 * loading/error state for the whole console. Disabled until the operator is
 * known to be an admin, so a denied session never probes the endpoints.
 */
export const useSettingsBundle = (enabled: boolean): SettingsBundle => {
  const notify = useNotify();

  const zalo = useQuery<ZaloSettings>({
    queryKey: integrationSettingsKeys.zalo,
    queryFn: () => zaloIntegrationGateway.loadZaloSettings(),
    enabled,
    staleTime: SETTINGS_STALE_TIME,
  });
  const minimax = useQuery<MinimaxSettings>({
    queryKey: integrationSettingsKeys.minimax,
    queryFn: () => zaloIntegrationGateway.loadMinimaxSettings(),
    enabled,
    staleTime: SETTINGS_STALE_TIME,
  });
  const openRouter = useQuery<OpenRouterSettings>({
    queryKey: integrationSettingsKeys.openRouter,
    queryFn: () => zaloIntegrationGateway.loadOpenRouterSettings(),
    enabled,
    staleTime: SETTINGS_STALE_TIME,
  });
  const customLlm = useQuery<CustomLlmSettings>({
    queryKey: integrationSettingsKeys.customLlm,
    queryFn: () => zaloIntegrationGateway.loadCustomLlmSettings(),
    enabled,
    staleTime: SETTINGS_STALE_TIME,
  });
  const jev = useQuery<JevSettings>({
    queryKey: integrationSettingsKeys.jev,
    queryFn: () => zaloIntegrationGateway.loadJevSettings(),
    enabled,
    staleTime: SETTINGS_STALE_TIME,
  });

  const queries = [zalo, minimax, openRouter, customLlm, jev];
  const isError = queries.some((query) => query.isError);
  const isPending = queries.some((query) => query.isPending);

  useEffect(() => {
    if (isError) {
      notify("Không thể tải cấu hình tích hợp.", { type: "error" });
    }
  }, [isError, notify]);

  const statusState: SettingsStatusState = isError
    ? "error"
    : isPending
      ? "loading"
      : "ready";

  return useMemo(
    () => ({
      zalo: zalo.data ?? null,
      providers: {
        minimax: minimax.data ?? null,
        openRouter: openRouter.data ?? null,
        customLlm: customLlm.data ?? null,
        jev: jev.data ?? null,
      },
      statusState,
    }),
    [
      zalo.data,
      minimax.data,
      openRouter.data,
      customLlm.data,
      jev.data,
      statusState,
    ],
  );
};
