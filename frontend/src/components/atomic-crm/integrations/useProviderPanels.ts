import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNotify } from "ra-core";

import type { LlmProvider, ProviderTestStatus } from "./api";
import {
  CHAIN_PANEL_ID_BY_PROVIDER,
  LLM_PROVIDER_ORDER,
  PROVIDER_GROUP_IDS,
  PROVIDER_PANELS,
  PROVIDER_PANELS_BY_ID,
  emptyProviderForm,
  normalizeFailoverOrder,
  resetProviderForm,
  type ProviderFormState,
  type ProviderLlmContext,
  type ProviderPanelGroup,
  type ProviderPanelId,
  type ProviderPayload,
  type ProviderSettingsBundle,
} from "./providerDescriptors";
import { integrationSettingsKeys } from "./useSettingsBundle";

const EMPTY_PROVIDER_ENABLED: Record<ProviderPanelId, boolean> = {
  minimax: true,
  openrouter: false,
  "custom-llm": false,
  jev: false,
};

const EMPTY_PROVIDER_BUSY: Record<ProviderPanelId, boolean> = {
  minimax: false,
  openrouter: false,
  "custom-llm": false,
  jev: false,
};

const EMPTY_GROUP_BUSY: Record<ProviderPanelGroup, boolean> = {
  chain: false,
  standalone: false,
};

/**
 * The provider-panel state and actions a settings section renders: one flat
 * draft form, the enable switches, the failover ranking and the
 * save/discard/probe actions.
 */
export type ProviderPanels = {
  providerForm: ProviderFormState;
  setProviderFormValue: (key: keyof ProviderFormState, value: string) => void;
  providerEnabled: Record<ProviderPanelId, boolean>;
  setPanelEnabled: (id: ProviderPanelId, checked: boolean) => void;
  handleProviderEnabledChange: (
    provider: LlmProvider,
    checked: boolean,
  ) => void;
  providerTesting: Record<ProviderPanelId, boolean>;
  providerSaving: Record<ProviderPanelGroup, boolean>;
  providerLastTests: Partial<Record<ProviderPanelId, ProviderTestStatus>>;
  llmDefaultProvider: LlmProvider;
  setLlmDefaultProvider: (provider: LlmProvider) => void;
  /** Displayed failover chain: the default first, then the ranked spares. */
  chain: LlmProvider[];
  chainEnabled: Record<LlmProvider, boolean>;
  moveProvider: (provider: LlmProvider, direction: -1 | 1) => void;
  dirty: Record<ProviderPanelGroup, boolean>;
  saveProviderPanels: (group: ProviderPanelGroup) => Promise<void>;
  discardProviderPanels: (group: ProviderPanelGroup) => void;
  testProviderPanel: (id: ProviderPanelId) => Promise<void>;
};

/**
 * Owns every LLM provider panel: the draft form, the enable switches, the
 * failover ranking and the save/discard/probe actions behind one descriptor
 * table. Saves go through TanStack Query mutations that write each PUT
 * response into the settings cache, so a panel never triggers a manual reload.
 */
export const useProviderPanels = (
  providers: ProviderSettingsBundle,
): ProviderPanels => {
  const notify = useNotify();
  const queryClient = useQueryClient();
  const [providerForm, setProviderForm] =
    useState<ProviderFormState>(emptyProviderForm());
  const [providerEnabled, setProviderEnabled] = useState<
    Record<ProviderPanelId, boolean>
  >(EMPTY_PROVIDER_ENABLED);
  const [providerTesting, setProviderTesting] =
    useState<Record<ProviderPanelId, boolean>>(EMPTY_PROVIDER_BUSY);
  const [providerSaving, setProviderSaving] =
    useState<Record<ProviderPanelGroup, boolean>>(EMPTY_GROUP_BUSY);
  const [providerLastTests, setProviderLastTests] = useState<
    Partial<Record<ProviderPanelId, ProviderTestStatus>>
  >({});
  const [llmDefaultProvider, setLlmDefaultProvider] =
    useState<LlmProvider>("minimax");
  const [llmFailoverOrder, setLlmFailoverOrder] = useState<LlmProvider[]>([
    ...LLM_PROVIDER_ORDER,
  ]);
  const seeded = useRef(false);
  const savingRef = useRef({ ...EMPTY_GROUP_BUSY });
  const testingRef = useRef({ ...EMPTY_PROVIDER_BUSY });

  // Seed once from the first complete bundle: panels, switches and the failover
  // chain all mirror one server snapshot, and a later background refetch must
  // not wipe an in-progress edit (same as the pre-refactor load).
  useEffect(() => {
    if (seeded.current) return;
    const { minimax, openRouter, customLlm, jev } = providers;
    if (!minimax || !openRouter || !customLlm || !jev) return;
    seeded.current = true;

    const nextEnabled = { ...EMPTY_PROVIDER_ENABLED };
    const nextLastTests: Partial<Record<ProviderPanelId, ProviderTestStatus>> =
      {};
    for (const descriptor of PROVIDER_PANELS) {
      const saved = descriptor.readEnabled(providers);
      if (saved !== null) nextEnabled[descriptor.id] = saved;
      const lastTest = descriptor.initialTest(providers);
      if (lastTest) nextLastTests[descriptor.id] = lastTest;
    }
    setProviderEnabled(nextEnabled);
    setProviderLastTests(nextLastTests);
    setLlmDefaultProvider(customLlm.llm_default_provider);
    setLlmFailoverOrder(normalizeFailoverOrder(customLlm.llm_failover_order));
    setProviderForm(resetProviderForm(providers));
  }, [providers]);

  const saveMutation = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: ProviderPanelId;
      payload: ProviderPayload;
    }) => PROVIDER_PANELS_BY_ID[id].save(payload),
    onSuccess: (saved, { id }) => {
      queryClient.setQueryData(
        integrationSettingsKeys[PROVIDER_PANELS_BY_ID[id].bundleKey],
        saved,
      );
    },
  });

  const testMutation = useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: ProviderPanelId;
      body?: Record<string, string>;
    }) => PROVIDER_PANELS_BY_ID[id].testConnection(body),
  });

  // Panel-global LLM-chain state the descriptors read and sync. Memoised so a
  // keystroke in any provider field does not hand every descriptor a fresh
  // context object.
  const llmContext: ProviderLlmContext = useMemo(
    () => ({
      defaultProvider: llmDefaultProvider,
      failoverOrder: llmFailoverOrder,
      setDefaultProvider: setLlmDefaultProvider,
      setFailoverOrder: setLlmFailoverOrder,
    }),
    [llmDefaultProvider, llmFailoverOrder],
  );

  // One dirty-check builder for every provider: secrets go out when non-empty,
  // text/select fields when they differ from their saved value, the enable
  // switch when it differs from the saved flag, plus any panel-global keys the
  // descriptor adds (default provider, failover order).
  const providerPayload = useCallback(
    (id: ProviderPanelId): ProviderPayload => {
      const descriptor = PROVIDER_PANELS_BY_ID[id];
      const savedEnabled = descriptor.readEnabled(providers);
      const payload: ProviderPayload = {};
      for (const field of descriptor.fields) {
        if (field.kind === "readonly") continue;
        const raw = providerForm[field.formKey].trim();
        if (field.kind === "secret") {
          if (raw) payload[field.formKey] = raw;
          continue;
        }
        // Saved settings must exist before a text/select/enable diff is legal.
        if (savedEnabled === null) continue;
        if (!raw || raw === field.saved(providers)) continue;
        const payloadKeys =
          field.kind === "select"
            ? (field.payloadKeys ?? [field.formKey])
            : [field.formKey];
        for (const key of payloadKeys) {
          payload[key] = raw;
        }
      }
      if (savedEnabled !== null && providerEnabled[id] !== savedEnabled) {
        payload[descriptor.enableKey] = providerEnabled[id];
      }
      if (descriptor.extraPayload) {
        Object.assign(payload, descriptor.extraPayload(llmContext, providers));
      }
      return payload;
    },
    [providerEnabled, providerForm, llmContext, providers],
  );

  const dirty = useMemo(() => {
    const byGroup: Record<ProviderPanelGroup, boolean> = {
      chain: false,
      standalone: false,
    };
    for (const group of Object.keys(byGroup) as ProviderPanelGroup[]) {
      byGroup[group] = PROVIDER_GROUP_IDS[group].some(
        (id) => Object.keys(providerPayload(id)).length > 0,
      );
    }
    return byGroup;
  }, [providerPayload]);

  // Displayed failover chain: the default starts every turn, the other
  // providers follow the operator-ranked spare order.
  const chain = useMemo<LlmProvider[]>(
    () => [
      llmDefaultProvider,
      ...llmFailoverOrder.filter((provider) => provider !== llmDefaultProvider),
    ],
    [llmDefaultProvider, llmFailoverOrder],
  );

  const chainEnabled = useMemo<Record<LlmProvider, boolean>>(
    () => ({
      minimax: providerEnabled.minimax,
      openrouter: providerEnabled.openrouter,
      custom: providerEnabled["custom-llm"],
    }),
    [providerEnabled],
  );

  const setProviderFormValue = (
    key: keyof ProviderFormState,
    value: string,
  ) => {
    setProviderForm((current) => ({ ...current, [key]: value }));
  };

  const setPanelEnabled = (id: ProviderPanelId, checked: boolean) => {
    setProviderEnabled((current) => ({ ...current, [id]: checked }));
  };

  const handleProviderEnabledChange = (
    provider: LlmProvider,
    checked: boolean,
  ) => {
    setPanelEnabled(CHAIN_PANEL_ID_BY_PROVIDER[provider], checked);

    // Walk the operator's ranked chain, not the canonical array: the panel
    // advertises that ranking as who takes over, and the backend chain builder
    // ranks by the same stored order. Picking canonically here would hand the
    // turn to a provider the operator deliberately ranked last.
    const otherEnabled = normalizeFailoverOrder(llmFailoverOrder).filter(
      (candidate) => candidate !== provider && chainEnabled[candidate],
    );
    // Disabling the default hands it to the next enabled provider in that
    // ranking; enabling the ONLY enabled provider makes it the default.
    if (!checked && llmDefaultProvider === provider && otherEnabled.length) {
      setLlmDefaultProvider(otherEnabled[0]);
    }
    if (checked && otherEnabled.length === 0) {
      setLlmDefaultProvider(provider);
    }
  };

  // Reorder within the displayed chain (default pinned at index 0 — it always
  // opens the turn); the stored ranking mirrors the displayed one.
  const moveProvider = (provider: LlmProvider, direction: -1 | 1) => {
    const index = chain.indexOf(provider);
    const target = index + direction;
    if (index < 1 || target < 1 || target >= chain.length) return;
    const next = [...chain];
    [next[index], next[target]] = [next[target], next[index]];
    setLlmFailoverOrder(next);
  };

  const saveProviderPanels = async (group: ProviderPanelGroup) => {
    if (savingRef.current[group]) return;
    // One save action per group, sequential PUTs: only the payloads that
    // actually changed go out; the default-provider radio rides the minimax
    // PUT.
    const descriptors = PROVIDER_GROUP_IDS[group].map(
      (id) => PROVIDER_PANELS_BY_ID[id],
    );
    if (
      descriptors.every(
        (descriptor) =>
          Object.keys(providerPayload(descriptor.id)).length === 0,
      )
    ) {
      return;
    }
    savingRef.current[group] = true;
    setProviderSaving((current) => ({ ...current, [group]: true }));
    try {
      let bundle = providers;
      for (const descriptor of descriptors) {
        const payload = providerPayload(descriptor.id);
        if (Object.keys(payload).length === 0) continue;
        const saved = await saveMutation.mutateAsync({
          id: descriptor.id,
          payload,
        });
        bundle = {
          ...bundle,
          [descriptor.bundleKey]: saved,
        } as ProviderSettingsBundle;
        descriptor.afterSaveSync?.(bundle, llmContext);
      }
      setProviderEnabled((current) => {
        const next = { ...current };
        for (const descriptor of descriptors) {
          const savedEnabled = descriptor.readEnabled(bundle);
          if (savedEnabled !== null) next[descriptor.id] = savedEnabled;
        }
        return next;
      });
      setProviderForm((current) =>
        resetProviderForm(bundle, descriptors, current),
      );
      notify("Đã lưu thay đổi", { type: "success" });
    } catch {
      notify("Không lưu được thay đổi.", { type: "error" });
    } finally {
      savingRef.current[group] = false;
      setProviderSaving((current) => ({ ...current, [group]: false }));
    }
  };

  const discardProviderPanels = (group: ProviderPanelGroup) => {
    if (savingRef.current[group]) return;
    const descriptors = PROVIDER_GROUP_IDS[group].map(
      (id) => PROVIDER_PANELS_BY_ID[id],
    );
    const nextEnabled = { ...providerEnabled };
    for (const descriptor of descriptors) {
      const savedEnabled = descriptor.readEnabled(providers);
      if (savedEnabled !== null) nextEnabled[descriptor.id] = savedEnabled;
      descriptor.discardSync?.(providers, llmContext);
    }
    setProviderEnabled(nextEnabled);
    setProviderForm((current) =>
      resetProviderForm(providers, descriptors, current),
    );
  };

  const testProviderPanel = async (id: ProviderPanelId) => {
    if (
      testingRef.current[id] ||
      savingRef.current[PROVIDER_PANELS_BY_ID[id].chrome]
    )
      return;
    testingRef.current[id] = true;
    const descriptor = PROVIDER_PANELS_BY_ID[id];
    setProviderTesting((current) => ({ ...current, [id]: true }));
    try {
      // Probe, never write: testing must not persist an untested credential.
      const result = await testMutation.mutateAsync({
        id,
        body: descriptor.buildTestBody?.(providerForm),
      });
      setProviderLastTests((current) => ({
        ...current,
        [id]: {
          ok: result.ok,
          latency_ms: result.latency_ms,
          tested_at: Math.floor(Date.now() / 1000),
          error: result.error,
        },
      }));
      if (result.ok) {
        notify(`Kết nối thành công (${result.latency_ms ?? "?"}ms)`, {
          type: "success",
        });
      } else if (!result.configured && result.missing.length > 0) {
        const missing = result.missing
          .map((key) => descriptor.testFieldLabels[key] ?? key)
          .join(", ");
        notify(`Thiếu cấu hình: ${missing}`, { type: "warning" });
      } else {
        notify(result.error || "Không kết nối được", { type: "error" });
      }
    } catch {
      const error = "Không kiểm tra được kết nối. Vui lòng thử lại.";
      setProviderLastTests((current) => ({
        ...current,
        [id]: {
          ok: false,
          latency_ms: null,
          tested_at: Math.floor(Date.now() / 1000),
          error,
        },
      }));
      notify(error, { type: "error" });
    } finally {
      testingRef.current[id] = false;
      setProviderTesting((current) => ({ ...current, [id]: false }));
    }
  };

  return {
    providerForm,
    setProviderFormValue,
    providerEnabled,
    setPanelEnabled,
    handleProviderEnabledChange,
    providerTesting,
    providerSaving,
    providerLastTests,
    llmDefaultProvider,
    setLlmDefaultProvider,
    chain,
    chainEnabled,
    moveProvider,
    dirty,
    saveProviderPanels,
    discardProviderPanels,
    testProviderPanel,
  };
};
