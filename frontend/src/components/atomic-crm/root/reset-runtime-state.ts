import { QueryClient } from "@tanstack/react-query";
import { localStorageStore } from "ra-core";

import { closeRealtimeSocket } from "../providers/realtime/realtime-socket";
import {
  buildStaticRecruitmentRuntime,
  getStaticRecruitmentRuntimeKey,
} from "../capabilities/static-recruitment-runtime";
import type { RuntimeGenerationBundle } from "../capabilities/types";
import {
  bindConversationRuntimeEpoch,
  resetConversationRuntimeState,
} from "../conversations/reset-runtime";
import { clearBotRunQueries } from "../automation/botRunQueries";

const LEGACY_ADAPTER_KEYS = [
  "vfic:chatops:saved-views:v1",
  "vfic:chatops:active-filter:v1",
  "vfic:chatops:recent-tags:v1",
  "app.configuration",
] as const;

let runtimeEpoch = 0;
let activeBundle: RuntimeGenerationBundle | null = null;
let inFlightKey: string | null = null;
let inFlightBundle: Promise<RuntimeGenerationBundle> | null = null;

export const getRuntimeEpoch = (): number => runtimeEpoch;
export const isRuntimeEpochCurrent = (epoch: number): boolean =>
  epoch === runtimeEpoch;

bindConversationRuntimeEpoch({
  capture: getRuntimeEpoch,
  isCurrent: isRuntimeEpochCurrent,
});
export const getActiveRuntimeBundle = (): RuntimeGenerationBundle | null =>
  activeBundle;

export const clearActiveBotRunQueries = (): void => {
  if (activeBundle) clearBotRunQueries(activeBundle.queryClient);
};

export const createRuntimeQueryClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: {
      queries: {
        // Served from cache for up to 30s — the same cadence as the polling
        // queries that refresh the dashboard and inbox on a timer.
        staleTime: 30_000,
        // Reads keep firing on a flaky Zalo/recruiter connection instead of
        // pausing, so the inbox keeps its socket-fed cache reachable.
        networkMode: "offlineFirst",
        // gcTime is deliberately left at the TanStack default (5 minutes).
        // Nothing persists the cache across reloads — the persister packages
        // are not wired up — so a longer window would only grow in-tab memory.
      },
      mutations: {
        // Deliberately NOT "offlineFirst". That mode fires the request while
        // the device is offline, then pauses and replays it on reconnect, so a
        // write the caller has already reported as failed can still land later
        // (duplicate reply, out-of-order mode change). The "online" default
        // sends nothing while offline and drains once on reconnect, which the
        // server's send_unknown guard then de-duplicates.
        networkMode: "online",
      },
    },
  });

const clearAdapterStorage = (): void => {
  if (typeof window === "undefined") return;
  for (const key of LEGACY_ADAPTER_KEYS) window.localStorage.removeItem(key);
};

export const resetActiveRuntimeState = async (): Promise<void> => {
  const previous = activeBundle;
  activeBundle = null;

  closeRealtimeSocket();
  runtimeEpoch += 1;
  resetConversationRuntimeState();

  if (previous) {
    clearBotRunQueries(previous.queryClient);
    await previous.queryClient.cancelQueries();
    previous.queryClient.getMutationCache().clear();
    previous.queryClient.clear();
    previous.store.teardown();
  }
  clearAdapterStorage();
};

const storeKeyFor = (runtimeKey: string): string => {
  let hash = 2166136261;
  for (let index = 0; index < runtimeKey.length; index += 1) {
    hash ^= runtimeKey.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `CRM:${(hash >>> 0).toString(16)}`;
};

export const ensureRuntimeGeneration = async (
  authorityGeneration: number,
): Promise<RuntimeGenerationBundle> => {
  const requestedKey = getStaticRecruitmentRuntimeKey(authorityGeneration);
  if (activeBundle?.key === requestedKey) return activeBundle;
  if (inFlightBundle) {
    if (inFlightKey === requestedKey) return inFlightBundle;
    await inFlightBundle.catch(() => undefined);
    return ensureRuntimeGeneration(authorityGeneration);
  }

  const operation = (async (): Promise<RuntimeGenerationBundle> => {
    if (activeBundle) await resetActiveRuntimeState();

    // Static runtime creation happens only after the previous generation has
    // been fully abandoned. A failure therefore stays neutral and cannot
    // restore a stale Admin generation.
    const activationEpoch = runtimeEpoch;
    const runtime = buildStaticRecruitmentRuntime(authorityGeneration);
    if (activationEpoch !== runtimeEpoch) {
      throw new Error("Runtime generation changed during materialization");
    }
    const bundle = Object.freeze({
      key: runtime.key,
      runtime,
      queryClient: createRuntimeQueryClient(),
      store: localStorageStore("1", storeKeyFor(runtime.key)),
    });
    activeBundle = bundle;
    return bundle;
  })();
  inFlightKey = requestedKey;
  inFlightBundle = operation;
  try {
    return await operation;
  } finally {
    if (inFlightBundle === operation) {
      inFlightBundle = null;
      inFlightKey = null;
    }
  }
};

export const abandonRuntimeGenerationForTests = (): void => {
  activeBundle = null;
  runtimeEpoch = 0;
  inFlightBundle = null;
  inFlightKey = null;
};
