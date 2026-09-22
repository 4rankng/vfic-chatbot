import { apiJson } from "@/lib/apiClient";
import type { ZaloFormState } from "./zaloUpdatePayload";

export type SecretStatus = { configured: boolean; preview?: string | null };
export type PlainStatus = { configured: boolean; value?: string | null };

export type ZaloOaSignatureHealth = {
  last_status: "verified" | "mismatched" | null;
  last_ts: number | null;
  last_mismatch_ts: number | null;
  consec_failures: number | null;
};

export type ZaloSettings = {
  zalo_bot_token: SecretStatus;
  zalo_bot_webhook_secret: SecretStatus;
  zalo_oa_app_id: PlainStatus;
  zalo_oa_secret_key: SecretStatus;
  zalo_oa_access_token: SecretStatus;
  zalo_oa_refresh_token: SecretStatus;
  zalo_bot_api_base: string;
  zalo_oa_api_base: string;
  zalo_oa_webhook_signature: ZaloOaSignatureHealth | null;
};

export type LlmProvider = "minimax" | "openrouter" | "custom";

/** Last real-probe outcome for one provider (persisted server-side). */
export type ProviderTestStatus = {
  ok: boolean;
  latency_ms: number | null;
  tested_at: number;
  error: string | null;
};

/** Uniform result of POST /{provider}/test for all three providers. */
export type ProviderTestResult = {
  configured: boolean;
  missing: string[];
  ok: boolean;
  latency_ms: number | null;
  sample: string | null;
  error: string | null;
};

export type MinimaxSettings = {
  minimax_api_key: SecretStatus;
  minimax_base_url: string;
  minimax_agent_model: string;
  minimax_safety_model: string;
  minimax_enable: boolean;
  llm_default_provider: LlmProvider;
  /** Operator-ranked spare order; the default provider always starts a turn. */
  llm_failover_order: LlmProvider[];
  last_test: ProviderTestStatus | null;
};

export type OpenRouterSettings = {
  openrouter_api_key: SecretStatus;
  openrouter_base_url: string;
  openrouter_agent_model: string;
  openrouter_safety_model: string;
  openrouter_digest_model: string;
  openrouter_enable: boolean;
  llm_default_provider: LlmProvider;
  llm_failover_order: LlmProvider[];
  last_test: ProviderTestStatus | null;
};

export type CustomLlmSettings = {
  custom_llm_api_key: SecretStatus;
  custom_llm_base_url: string;
  custom_llm_agent_model: string;
  custom_llm_safety_model: string;
  custom_llm_fast_model: string;
  custom_llm_label: string;
  /** Operator-declared model context window (tokens); null = server default. */
  custom_llm_context_window: number | null;
  custom_llm_enable: boolean;
  /** True only when enabled AND key + base URL + agent model are all present. */
  custom_llm_usable: boolean;
  llm_default_provider: LlmProvider;
  llm_failover_order: LlmProvider[];
  last_test: ProviderTestStatus | null;
};

export type JevSettings = {
  jev_api_key: SecretStatus;
  jev_model: string;
  jev_enable: boolean;
  /** True only when enabled AND the TypeSafe API key is present. */
  jev_usable: boolean;
};

export type ZaloChannelTestResult = {
  configured: boolean;
  connected: boolean;
  missing: string[];
  errors: string[];
  oa_secret_valid?: boolean | null;
  oa_refresh_ok?: boolean | null;
  oa_token_expired?: boolean | null;
};

export type IntegrationConfigTestResult = {
  configured: boolean;
  missing: string[];
};

export type FacebookAccountStatus = {
  /** Full Page id (unmasked; contract: additive). Key for per-Page routes. */
  page_id: string;
  page_id_suffix: string;
  label: string;
  status: "ACTIVE" | "INACTIVE";
};

/** Per-Page Project assignment list (GET /facebook/pages/{page_id}/projects). */
export type FacebookPageProjects = {
  page_id: string;
  assignments: Array<{
    project_id: string;
    project_slug?: string;
  }>;
};

export type FacebookIntegrationStatus = {
  enabled: boolean;
  accounts: FacebookAccountStatus[];
};

export type FacebookOAuthStart = {
  authorization_url: string;
};

export type FacebookPage = {
  id: string;
  name: string;
};

export type FacebookPageList = {
  pages: FacebookPage[];
  /** All currently-active Pages (contract: active_page_id is removed). */
  active_page_ids: string[];
};

export type FacebookOAuthCompleteRequest = {
  flow_id: string;
  page_id: string;
  /** Replace-all assignment set, applied atomically with activation (D1). */
  project_ids?: string[];
};

export type FacebookChannelTest = {
  healthy: boolean;
  error: string | null;
  // null/undefined = subscription lookup not run; false = app not subscribed.
  app_subscribed?: boolean | null;
};

export type FacebookCredentials = {
  facebook_app_id: PlainStatus;
  facebook_app_secret: SecretStatus;
  facebook_login_config_id: PlainStatus;
  facebook_webhook_verify_token: SecretStatus;
};

export type FacebookCredentialsReveal = {
  facebook_app_secret: string | null;
  facebook_webhook_verify_token: string | null;
};

export type FacebookCredentialsUpdate = {
  facebook_app_id?: string;
  facebook_app_secret?: string;
  facebook_login_config_id?: string;
  facebook_webhook_verify_token?: string;
};

const ADMIN_INTEGRATIONS_BASE_PATH = "/api/v1/admin/integrations";

const getFacebookOAuthPagesPath = (flowId: string): string =>
  `${ADMIN_INTEGRATIONS_BASE_PATH}/facebook/oauth/pages?flow_id=${encodeURIComponent(flowId)}`;

export const zaloIntegrationGateway = {
  loadSettingsBundle: async (): Promise<{
    zalo: ZaloSettings;
    minimax: MinimaxSettings;
    openRouter: OpenRouterSettings;
    customLlm: CustomLlmSettings;
    jev: JevSettings;
  }> => {
    const [zalo, minimax, openRouter, customLlm, jev] = await Promise.all([
      apiJson<ZaloSettings>(`${ADMIN_INTEGRATIONS_BASE_PATH}/zalo`),
      apiJson<MinimaxSettings>(`${ADMIN_INTEGRATIONS_BASE_PATH}/minimax`),
      apiJson<OpenRouterSettings>(`${ADMIN_INTEGRATIONS_BASE_PATH}/openrouter`),
      apiJson<CustomLlmSettings>(`${ADMIN_INTEGRATIONS_BASE_PATH}/custom-llm`),
      apiJson<JevSettings>(`${ADMIN_INTEGRATIONS_BASE_PATH}/jev`),
    ]);
    return { zalo, minimax, openRouter, customLlm, jev };
  },

  saveZaloSettings: async (
    body: Partial<ZaloFormState>,
  ): Promise<ZaloSettings> =>
    apiJson<ZaloSettings>(`${ADMIN_INTEGRATIONS_BASE_PATH}/zalo`, {
      method: "PUT",
      body,
    }),

  saveMinimaxSettings: async (
    body: Partial<{
      minimax_api_key: string;
      minimax_enable: boolean;
      llm_default_provider: LlmProvider;
      llm_failover_order: LlmProvider[];
    }>,
  ): Promise<MinimaxSettings> =>
    apiJson<MinimaxSettings>(`${ADMIN_INTEGRATIONS_BASE_PATH}/minimax`, {
      method: "PUT",
      body,
    }),

  saveOpenRouterSettings: async (
    body: Partial<{
      openrouter_api_key: string;
      openrouter_enable: boolean;
      openrouter_agent_model: string;
      openrouter_safety_model: string;
      openrouter_digest_model: string;
      llm_default_provider: LlmProvider;
    }>,
  ): Promise<OpenRouterSettings> =>
    apiJson<OpenRouterSettings>(`${ADMIN_INTEGRATIONS_BASE_PATH}/openrouter`, {
      method: "PUT",
      body,
    }),

  testBotConnection: async (): Promise<ZaloChannelTestResult> =>
    apiJson<ZaloChannelTestResult>(
      `${ADMIN_INTEGRATIONS_BASE_PATH}/zalo/bot/test`,
      { method: "POST" },
    ),

  testOaConnection: async (): Promise<ZaloChannelTestResult> =>
    apiJson<ZaloChannelTestResult>(
      `${ADMIN_INTEGRATIONS_BASE_PATH}/zalo/oa/test`,
      { method: "POST" },
    ),

  testMinimaxConnection: async (): Promise<ProviderTestResult> =>
    apiJson<ProviderTestResult>(
      `${ADMIN_INTEGRATIONS_BASE_PATH}/minimax/test`,
      { method: "POST" },
    ),

  testOpenRouterConnection: async (): Promise<ProviderTestResult> =>
    apiJson<ProviderTestResult>(
      `${ADMIN_INTEGRATIONS_BASE_PATH}/openrouter/test`,
      { method: "POST" },
    ),

  saveCustomLlmSettings: async (
    body: Partial<{
      custom_llm_api_key: string;
      custom_llm_base_url: string;
      custom_llm_agent_model: string;
      custom_llm_context_window: string;
      custom_llm_enable: boolean;
      llm_default_provider: LlmProvider;
    }>,
  ): Promise<CustomLlmSettings> =>
    apiJson<CustomLlmSettings>(`${ADMIN_INTEGRATIONS_BASE_PATH}/custom-llm`, {
      method: "PUT",
      body,
    }),

  testCustomLlmConnection: async (
    body?: Partial<{
      custom_llm_api_key: string;
      custom_llm_base_url: string;
      custom_llm_agent_model: string;
    }>,
  ): Promise<ProviderTestResult> =>
    apiJson<ProviderTestResult>(
      `${ADMIN_INTEGRATIONS_BASE_PATH}/custom-llm/test`,
      { method: "POST", body: body ?? {} },
    ),

  saveJevSettings: async (
    body: Partial<{
      jev_api_key: string;
      jev_model: string;
      jev_enable: boolean;
    }>,
  ): Promise<JevSettings> =>
    apiJson<JevSettings>(`${ADMIN_INTEGRATIONS_BASE_PATH}/jev`, {
      method: "PUT",
      body,
    }),

  testJevConnection: async (): Promise<ProviderTestResult> =>
    apiJson<ProviderTestResult>(`${ADMIN_INTEGRATIONS_BASE_PATH}/jev/test`, {
      method: "POST",
    }),
} as const;

export const facebookIntegrationGateway = {
  loadStatus: async (): Promise<FacebookIntegrationStatus> =>
    apiJson<FacebookIntegrationStatus>(
      `${ADMIN_INTEGRATIONS_BASE_PATH}/facebook`,
    ),

  loadCredentials: async (): Promise<FacebookCredentials> =>
    apiJson<FacebookCredentials>(
      `${ADMIN_INTEGRATIONS_BASE_PATH}/facebook/credentials`,
    ),

  // Plaintext secrets for an admin re-registering the webhook on Meta. Kept
  // out of the cached credentials query so the values are fetched only on an
  // explicit reveal and never linger in the query cache.
  revealCredentials: async (): Promise<FacebookCredentialsReveal> =>
    apiJson<FacebookCredentialsReveal>(
      `${ADMIN_INTEGRATIONS_BASE_PATH}/facebook/credentials/reveal`,
      { method: "POST" },
    ),

  saveCredentials: async (
    body: FacebookCredentialsUpdate,
  ): Promise<FacebookCredentials> =>
    apiJson<FacebookCredentials>(
      `${ADMIN_INTEGRATIONS_BASE_PATH}/facebook/credentials`,
      { method: "PUT", body },
    ),

  loadOAuthPages: async (flowId: string): Promise<FacebookPageList> =>
    apiJson<FacebookPageList>(getFacebookOAuthPagesPath(flowId)),

  startOAuth: async (): Promise<FacebookOAuthStart> =>
    apiJson<FacebookOAuthStart>(
      `${ADMIN_INTEGRATIONS_BASE_PATH}/facebook/oauth/start`,
      { method: "POST" },
    ),

  completeOAuth: async (
    body: FacebookOAuthCompleteRequest,
  ): Promise<FacebookAccountStatus> =>
    apiJson<FacebookAccountStatus>(
      `${ADMIN_INTEGRATIONS_BASE_PATH}/facebook/oauth/complete`,
      { method: "POST", body },
    ),

  testConnection: async (): Promise<FacebookChannelTest> =>
    apiJson<FacebookChannelTest>(
      `${ADMIN_INTEGRATIONS_BASE_PATH}/facebook/test`,
      {
        method: "POST",
      },
    ),

  /**
   * Page↔Project assignment surface (multi-Page contract). Keyed by the full,
   * unmasked `page_id` exposed by GET /facebook.
   */
  loadPageProjects: async (pageId: string): Promise<FacebookPageProjects> =>
    apiJson<FacebookPageProjects>(
      `${ADMIN_INTEGRATIONS_BASE_PATH}/facebook/pages/${encodeURIComponent(pageId)}/projects`,
    ),

  /** Replace-all save for the per-Page multi-select editor. */
  setPageProjects: async (
    pageId: string,
    projectIds: string[],
  ): Promise<FacebookPageProjects> =>
    apiJson<FacebookPageProjects>(
      `${ADMIN_INTEGRATIONS_BASE_PATH}/facebook/pages/${encodeURIComponent(pageId)}/projects`,
      { method: "PUT", body: { project_ids: projectIds } },
    ),

  /** Disconnect one Page; the legacy single-Page behavior needs no param. */
  disconnectPage: async (pageId: string): Promise<FacebookAccountStatus> =>
    apiJson<FacebookAccountStatus>(
      `${ADMIN_INTEGRATIONS_BASE_PATH}/facebook?page_id=${encodeURIComponent(pageId)}`,
      { method: "DELETE" },
    ),
} as const;
