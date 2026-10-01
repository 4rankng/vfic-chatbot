import { Brain, type LucideIcon } from "lucide-react";

import {
  zaloIntegrationGateway,
  type CustomLlmSettings,
  type JevSettings,
  type LlmProvider,
  type MinimaxSettings,
  type OpenRouterSettings,
  type ProviderTestResult,
  type ProviderTestStatus,
  type SecretStatus,
} from "./api";

// ---------------------------------------------------------------------------
// Provider settings panels (descriptor-driven)
//
// The four LLM-model-like providers (minimax, openrouter, custom-llm, jev)
// share one dirty-check/save/probe/status implementation. Each provider is a
// single declarative descriptor below; adding provider #6 means adding one
// entry, not another parallel slice of state and handlers.
//
// The descriptors carry their own gateway call so a new provider stays one
// entry; the application hooks own the state that drives them.
// ---------------------------------------------------------------------------

/** Form keys are unique across providers, so one flat form record serves all. */
export type ProviderFormState = {
  minimax_api_key: string;
  openrouter_api_key: string;
  openrouter_agent_model: string;
  embedding_provider: string;
  embedding_gemini_api_key: string;
  custom_llm_api_key: string;
  custom_llm_base_url: string;
  custom_llm_agent_model: string;
  jev_api_key: string;
  jev_model: string;
};

export type ProviderSettingsBundle = {
  minimax: MinimaxSettings | null;
  openRouter: OpenRouterSettings | null;
  customLlm: CustomLlmSettings | null;
  jev: JevSettings | null;
};

export type ProviderPanelId = "minimax" | "openrouter" | "custom-llm" | "jev";

/** Chain cards render in the failover ranking; standalone (jev) does not. */
export type ProviderPanelGroup = "chain" | "standalone";

export type ProviderPayloadValue = string | boolean | string[];
export type ProviderPayload = Record<string, ProviderPayloadValue>;

/** Shared LLM-chain state the panel-global radio/failover ranking rides on. */
export type ProviderLlmContext = {
  defaultProvider: LlmProvider;
  failoverOrder: LlmProvider[];
  setDefaultProvider: (provider: LlmProvider) => void;
  setFailoverOrder: (order: LlmProvider[]) => void;
};

export type ProviderFieldDescriptor =
  | {
      kind: "secret";
      formKey: keyof ProviderFormState;
      label: string;
      placeholder: string;
      status: (bundle: ProviderSettingsBundle) => SecretStatus;
    }
  | {
      kind: "text";
      formKey: keyof ProviderFormState;
      label: string;
      placeholder: (bundle: ProviderSettingsBundle) => string;
      saved: (bundle: ProviderSettingsBundle) => string;
    }
  | {
      kind: "select";
      formKey: keyof ProviderFormState;
      label: string;
      options: readonly string[];
      saved: (bundle: ProviderSettingsBundle) => string;
      /** OpenRouter fans one model choice out to agent/extractor/digest keys. */
      payloadKeys?: readonly string[];
    }
  | {
      kind: "readonly";
      label: string;
      note?: string;
      value: (bundle: ProviderSettingsBundle) => string;
    };

export type ProviderPanelDescriptor = {
  id: ProviderPanelId;
  /** Slice of {@link ProviderSettingsBundle} this provider owns. */
  bundleKey: keyof ProviderSettingsBundle;
  chrome: ProviderPanelGroup;
  title: string;
  description?: string;
  /** Standalone-card icon; chain cards render a rank badge instead. */
  icon?: LucideIcon;
  /** Standalone-card group status (configured/total); chain cards use chips. */
  status?: (
    bundle: ProviderSettingsBundle,
    enabled: boolean,
  ) => { configured: number; total: number; disabled: boolean };
  fields: readonly ProviderFieldDescriptor[];
  /** Switch id and PUT payload key ("minimax_enable", ...). */
  enableKey: string;
  /** Saved enable flag; null = settings not loaded yet. */
  readEnabled: (bundle: ProviderSettingsBundle) => boolean | null;
  initialTest: (bundle: ProviderSettingsBundle) => ProviderTestStatus | null;
  testFieldLabels: Record<string, string>;
  testConnection: (
    body?: Record<string, string>,
  ) => Promise<ProviderTestResult>;
  buildTestBody?: (form: ProviderFormState) => Record<string, string>;
  save: (
    payload: ProviderPayload,
  ) => Promise<
    MinimaxSettings | OpenRouterSettings | CustomLlmSettings | JevSettings
  >;
  /** Panel-global keys (default provider, failover order) beyond fields. */
  extraPayload?: (
    llm: ProviderLlmContext,
    bundle: ProviderSettingsBundle,
  ) => ProviderPayload;
  /** Post-save sync of panel-global state from the freshly saved settings. */
  afterSaveSync?: (
    bundle: ProviderSettingsBundle,
    llm: ProviderLlmContext,
  ) => void;
  /** Discard-time sync of panel-global state from the saved settings. */
  discardSync?: (
    bundle: ProviderSettingsBundle,
    llm: ProviderLlmContext,
  ) => void;
};

export const emptyProviderForm = (): ProviderFormState => ({
  minimax_api_key: "",
  openrouter_api_key: "",
  openrouter_agent_model: "deepseek/deepseek-v4-flash",
  embedding_provider: "openrouter",
  embedding_gemini_api_key: "",
  custom_llm_api_key: "",
  custom_llm_base_url: "",
  custom_llm_agent_model: "",
  jev_api_key: "",
  jev_model: "",
});

type MinimaxUpdatePayload = {
  minimax_api_key?: string;
  minimax_enable?: boolean;
  llm_default_provider?: LlmProvider;
  llm_failover_order?: LlmProvider[];
};

type CustomLlmUpdatePayload = {
  custom_llm_api_key?: string;
  custom_llm_base_url?: string;
  custom_llm_agent_model?: string;
  custom_llm_enable?: boolean;
  llm_default_provider?: LlmProvider;
};

type OpenRouterUpdatePayload = {
  openrouter_api_key?: string;
  openrouter_enable?: boolean;
  openrouter_agent_model?: string;
  openrouter_extractor_model?: string;
  openrouter_digest_model?: string;
  llm_default_provider?: LlmProvider;
  embedding_provider?: "openrouter" | "gemini";
  embedding_gemini_api_key?: string;
};

type JevUpdatePayload = {
  jev_api_key?: string;
  jev_model?: string;
  jev_enable?: boolean;
};

const OPENROUTER_MODEL_OPTIONS = [
  "deepseek/deepseek-v4-flash",
  "deepseek/deepseek-chat",
  "deepseek/deepseek-r1",
];

// Canonical provider order. It seeds an operator who has never ranked the
// chain and completes a partial ranking; once a ranking exists, that ranking —
// not this array — decides who starts a turn and who takes over.
export const LLM_PROVIDER_ORDER: readonly LlmProvider[] = [
  "minimax",
  "openrouter",
  "custom",
];

// Mirror of the backend normalizer: drop unknown names, dedupe, and append
// anything unranked in canonical order, so the stored ranking is always full.
export const normalizeFailoverOrder = (order: LlmProvider[]): LlmProvider[] => {
  const ranked = order.filter(
    (provider, index) =>
      LLM_PROVIDER_ORDER.includes(provider) &&
      order.indexOf(provider) === index,
  );
  return [
    ...ranked,
    ...LLM_PROVIDER_ORDER.filter((provider) => !ranked.includes(provider)),
  ];
};

export const MINIMAX_PANEL: ProviderPanelDescriptor = {
  id: "minimax",
  bundleKey: "minimax",
  chrome: "chain",
  title: "MiniMax",
  enableKey: "minimax_enable",
  readEnabled: (bundle) => bundle.minimax?.minimax_enable ?? null,
  initialTest: (bundle) => bundle.minimax?.last_test ?? null,
  fields: [
    {
      kind: "readonly",
      label: "Model chatbot",
      note: "Cố định",
      value: (bundle) => bundle.minimax?.minimax_agent_model ?? "—",
    },
    {
      kind: "secret",
      formKey: "minimax_api_key",
      label: "Access Token",
      placeholder: "Dán token Minimax",
      status: (bundle) =>
        bundle.minimax?.minimax_api_key ?? { configured: false },
    },
  ],
  testFieldLabels: { minimax_api_key: "Access Token" },
  testConnection: () => zaloIntegrationGateway.testMinimaxConnection(),
  save: (payload) =>
    zaloIntegrationGateway.saveMinimaxSettings(payload as MinimaxUpdatePayload),
  extraPayload: (llm, bundle) => {
    const payload: ProviderPayload = {};
    const settings = bundle.minimax;
    if (!settings) return payload;
    // The default-provider radio is panel-global; a change rides exactly one
    // PUT (minimax) so three payloads never write the shared key twice. The
    // spare ranking shares that PUT.
    if (llm.defaultProvider !== settings.llm_default_provider) {
      payload.llm_default_provider = llm.defaultProvider;
    }
    if (llm.failoverOrder.join(",") !== settings.llm_failover_order.join(",")) {
      payload.llm_failover_order = llm.failoverOrder;
    }
    return payload;
  },
  afterSaveSync: (bundle, llm) => {
    const next = bundle.minimax;
    if (!next) return;
    llm.setDefaultProvider(next.llm_default_provider);
    llm.setFailoverOrder(normalizeFailoverOrder(next.llm_failover_order));
  },
};

export const OPENROUTER_PANEL: ProviderPanelDescriptor = {
  id: "openrouter",
  bundleKey: "openRouter",
  chrome: "chain",
  title: "OpenRouter",
  enableKey: "openrouter_enable",
  readEnabled: (bundle) => bundle.openRouter?.openrouter_enable ?? null,
  initialTest: (bundle) => bundle.openRouter?.last_test ?? null,
  fields: [
    {
      kind: "select",
      formKey: "openrouter_agent_model",
      label: "Model chatbot",
      options: OPENROUTER_MODEL_OPTIONS,
      saved: (bundle) => bundle.openRouter?.openrouter_agent_model ?? "",
      payloadKeys: [
        "openrouter_agent_model",
        "openrouter_extractor_model",
        "openrouter_digest_model",
      ],
    },
    {
      kind: "secret",
      formKey: "openrouter_api_key",
      label: "Access Token",
      placeholder: "Dán token OpenRouter",
      status: (bundle) =>
        bundle.openRouter?.openrouter_api_key ?? { configured: false },
    },
    {
      kind: "select",
      formKey: "embedding_provider",
      label: "Nhà cung cấp Embedding",
      options: ["openrouter", "gemini"],
      saved: (bundle) => bundle.openRouter?.embedding_provider ?? "openrouter",
    },
    {
      kind: "secret",
      formKey: "embedding_gemini_api_key",
      label: "Gemini API Key",
      placeholder: "Dán key Gemini",
      status: (bundle) =>
        bundle.openRouter?.embedding_gemini_api_key ?? { configured: false },
    },
  ],
  testFieldLabels: { openrouter_api_key: "Access Token" },
  testConnection: () => zaloIntegrationGateway.testOpenRouterConnection(),
  save: (payload) =>
    zaloIntegrationGateway.saveOpenRouterSettings(
      payload as OpenRouterUpdatePayload,
    ),
};

export const CUSTOM_LLM_PANEL: ProviderPanelDescriptor = {
  id: "custom-llm",
  bundleKey: "customLlm",
  chrome: "chain",
  title: "Xiaomi",
  enableKey: "custom_llm_enable",
  readEnabled: (bundle) => bundle.customLlm?.custom_llm_enable ?? null,
  initialTest: (bundle) => bundle.customLlm?.last_test ?? null,
  fields: [
    {
      kind: "text",
      formKey: "custom_llm_base_url",
      label: "Base URL",
      placeholder: (bundle) =>
        bundle.customLlm?.custom_llm_base_url ||
        "https://token-plan-sgp.xiaomimimo.com/v1",
      saved: (bundle) => bundle.customLlm?.custom_llm_base_url ?? "",
    },
    {
      kind: "text",
      formKey: "custom_llm_agent_model",
      label: "Model chatbot",
      placeholder: (bundle) =>
        bundle.customLlm?.custom_llm_agent_model || "mimo-v2.5-pro",
      saved: (values) => values.customLlm?.custom_llm_agent_model ?? "",
    },
    {
      kind: "secret",
      formKey: "custom_llm_api_key",
      label: "Access Token",
      placeholder: "Dán token Xiaomi",
      status: (bundle) =>
        bundle.customLlm?.custom_llm_api_key ?? { configured: false },
    },
  ],
  testFieldLabels: {
    custom_llm_api_key: "Access Token",
    custom_llm_base_url: "Base URL",
    custom_llm_agent_model: "Model chatbot",
  },
  testConnection: (body) =>
    zaloIntegrationGateway.testCustomLlmConnection(body),
  buildTestBody: (form) =>
    Object.fromEntries(
      (
        [
          ["custom_llm_api_key", form.custom_llm_api_key],
          ["custom_llm_base_url", form.custom_llm_base_url],
          ["custom_llm_agent_model", form.custom_llm_agent_model],
        ] as const
      )
        .map(([key, raw]) => [key, raw.trim()] as const)
        .filter(([, value]) => value !== ""),
    ),
  save: (payload) =>
    zaloIntegrationGateway.saveCustomLlmSettings(
      payload as CustomLlmUpdatePayload,
    ),
  discardSync: (bundle, llm) => {
    const settings = bundle.customLlm;
    if (!settings) return;
    llm.setDefaultProvider(settings.llm_default_provider);
    llm.setFailoverOrder(normalizeFailoverOrder(settings.llm_failover_order));
  },
};

export const JEV_PANEL: ProviderPanelDescriptor = {
  id: "jev",
  bundleKey: "jev",
  chrome: "standalone",
  title: "Jev (TypeSafe)",
  description:
    "Mô hình quyết định System One — phân loại ý định, hướng sắp xếp, và nhận diện lời xã giao cho bot. Bot vẫn hoạt động bình thường khi Jev tắt.",
  icon: Brain,
  status: (bundle, enabled) => ({
    configured: [
      bundle.jev?.jev_api_key.configured,
      Boolean(bundle.jev?.jev_model),
    ].filter(Boolean).length,
    total: 2,
    disabled: !enabled,
  }),
  enableKey: "jev_enable",
  readEnabled: (bundle) => bundle.jev?.jev_enable ?? null,
  initialTest: () => null,
  fields: [
    {
      kind: "text",
      formKey: "jev_model",
      label: "Model",
      placeholder: (bundle) => bundle.jev?.jev_model || "jev-latest",
      saved: (bundle) => bundle.jev?.jev_model ?? "",
    },
    {
      kind: "secret",
      formKey: "jev_api_key",
      label: "API Key",
      placeholder: "Dán API key TypeSafe",
      status: (bundle) => bundle.jev?.jev_api_key ?? { configured: false },
    },
  ],
  testFieldLabels: { jev_api_key: "API Key", jev_model: "Model" },
  testConnection: () => zaloIntegrationGateway.testJevConnection(),
  save: (payload) =>
    zaloIntegrationGateway.saveJevSettings(payload as JevUpdatePayload),
};

export const PROVIDER_PANELS: readonly ProviderPanelDescriptor[] = [
  MINIMAX_PANEL,
  OPENROUTER_PANEL,
  CUSTOM_LLM_PANEL,
  JEV_PANEL,
];

export const PROVIDER_PANELS_BY_ID: Record<
  ProviderPanelId,
  ProviderPanelDescriptor
> = {
  minimax: MINIMAX_PANEL,
  openrouter: OPENROUTER_PANEL,
  "custom-llm": CUSTOM_LLM_PANEL,
  jev: JEV_PANEL,
};

export const PROVIDER_GROUP_IDS: Record<
  ProviderPanelGroup,
  readonly ProviderPanelId[]
> = {
  chain: PROVIDER_PANELS.filter((panel) => panel.chrome === "chain").map(
    (panel) => panel.id,
  ),
  standalone: PROVIDER_PANELS.filter(
    (panel) => panel.chrome === "standalone",
  ).map((panel) => panel.id),
};

export const CHAIN_PANEL_ID_BY_PROVIDER: Record<LlmProvider, ProviderPanelId> =
  {
    minimax: "minimax",
    openrouter: "openrouter",
    custom: "custom-llm",
  };

/**
 * Per-field reset values for the provider form: secret fields clear (they are
 * masked), while text and select fields re-sync to their saved value so the
 * operator sees what is stored — an empty text input both hides the saved value
 * and invites browser autofill (a stray email), which then reads as a phantom
 * edit. Scoped to the given panels so a chain save never wipes an in-progress
 * Jev edit (and vice versa), matching the pre-refactor behavior.
 */
export const resetProviderForm = (
  bundle: ProviderSettingsBundle,
  panels: readonly ProviderPanelDescriptor[] = PROVIDER_PANELS,
  current: ProviderFormState = emptyProviderForm(),
): ProviderFormState => {
  const form = { ...current };
  for (const descriptor of panels) {
    for (const field of descriptor.fields) {
      if (field.kind === "readonly") continue;
      form[field.formKey] = field.kind === "secret" ? "" : field.saved(bundle);
    }
  }
  return form;
};
