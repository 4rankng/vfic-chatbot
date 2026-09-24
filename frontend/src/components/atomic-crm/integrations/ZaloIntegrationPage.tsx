import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useNotify, usePermissions, useTranslate } from "ra-core";
import {
  Bot,
  Brain,
  ChevronDown,
  ChevronUp,
  Copy,
  Menu,
  MessageCircle,
  MessagesSquare,
  PlugZap,
  UsersRound,
  Wifi,
  Workflow,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  zaloIntegrationGateway,
  type CustomLlmSettings,
  type JevSettings,
  type LlmProvider,
  type ProviderTestResult,
  type ProviderTestStatus,
  type MinimaxSettings,
  type OpenRouterSettings,
  type SecretStatus,
  type ZaloChannelTestResult,
  type ZaloOaSignatureHealth,
  type ZaloSettings,
} from "./api";
import {
  buildZaloUpdatePayload,
  type ZaloFormState,
  type ZaloSettingsScope,
} from "./zaloUpdatePayload";
import { useIsMobile } from "@/hooks/use-mobile";
import { PersonaList } from "../personas/PersonaList";
import { UserList } from "../users/UserList";
import { FacebookMessengerIntegrationPage } from "./FacebookMessengerIntegrationPage";
import {
  copyCredentialFieldValue,
  CredentialSecretField,
  type CredentialFieldNotify,
} from "./CredentialSecretField";
import {
  SettingsFieldStatus,
  SettingsGroupStatus,
  type SettingsStatusState,
} from "./SettingsFieldStatus";
import "../conversations/inbox.css";
import "./settings.css";

type FormState = ZaloFormState;

// ---------------------------------------------------------------------------
// Provider settings panels (descriptor-driven)
//
// The four LLM-model-like providers (minimax, openrouter, custom-llm, jev)
// share one dirty-check/save/probe/status implementation. Each provider is a
// single declarative descriptor below; adding provider #6 means adding one
// entry, not another parallel slice of state and handlers.
// ---------------------------------------------------------------------------

/** Form keys are unique across providers, so one flat form record serves all. */
type ProviderFormState = {
  minimax_api_key: string;
  openrouter_api_key: string;
  openrouter_agent_model: string;
  custom_llm_api_key: string;
  custom_llm_base_url: string;
  custom_llm_agent_model: string;
  jev_api_key: string;
  jev_model: string;
};

type ProviderSettingsBundle = {
  minimax: MinimaxSettings | null;
  openRouter: OpenRouterSettings | null;
  customLlm: CustomLlmSettings | null;
  jev: JevSettings | null;
};

type ProviderPanelId = "minimax" | "openrouter" | "custom-llm" | "jev";

/** Chain cards render in the failover ranking; standalone (jev) does not. */
type ProviderPanelGroup = "chain" | "standalone";

type ProviderPayloadValue = string | boolean | string[];
type ProviderPayload = Record<string, ProviderPayloadValue>;

/** Shared LLM-chain state the panel-global radio/failover ranking rides on. */
type ProviderLlmContext = {
  defaultProvider: LlmProvider;
  failoverOrder: LlmProvider[];
  setDefaultProvider: (provider: LlmProvider) => void;
  setFailoverOrder: (order: LlmProvider[]) => void;
};

type ProviderFieldDescriptor =
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
      /** OpenRouter fans one model choice out to agent/safety/digest keys. */
      payloadKeys?: readonly string[];
    }
  | {
      kind: "readonly";
      label: string;
      note?: string;
      value: (bundle: ProviderSettingsBundle) => string;
    };

type ProviderPanelDescriptor = {
  id: ProviderPanelId;
  /** Slice of {@link ProviderSettingsBundle} this provider owns. */
  bundleKey: keyof ProviderSettingsBundle;
  chrome: ProviderPanelGroup;
  title: string;
  description?: string;
  /** Standalone-card icon; chain cards render a rank badge instead. */
  icon?: ReactNode;
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

const emptyProviderForm = (): ProviderFormState => ({
  minimax_api_key: "",
  openrouter_api_key: "",
  openrouter_agent_model: "deepseek/deepseek-v4-flash",
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
  openrouter_safety_model?: string;
  openrouter_digest_model?: string;
  llm_default_provider?: LlmProvider;
};

type JevUpdatePayload = {
  jev_api_key?: string;
  jev_model?: string;
  jev_enable?: boolean;
};

const emptyForm: FormState = {
  zalo_bot_token: "",
  zalo_bot_webhook_secret: "",
  zalo_oa_app_id: "",
  zalo_oa_secret_key: "",
  zalo_oa_access_token: "",
  zalo_oa_refresh_token: "",
};

const ZALO_TEST_FIELD_LABELS: Record<string, string> = {
  zalo_bot_token: "Bot Token",
  zalo_oa_app_id: "Zalo App ID",
  zalo_oa_secret_key: "Bot Secret",
  zalo_oa_access_token: "OA Access Token",
  zalo_oa_refresh_token: "OA Refresh Token",
};

const OPENROUTER_MODEL_OPTIONS = [
  "deepseek/deepseek-v4-flash",
  "deepseek/deepseek-chat",
  "deepseek/deepseek-r1",
];

const MINIMAX_PANEL: ProviderPanelDescriptor = {
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

const OPENROUTER_PANEL: ProviderPanelDescriptor = {
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
        "openrouter_safety_model",
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
  ],
  testFieldLabels: { openrouter_api_key: "Access Token" },
  testConnection: () => zaloIntegrationGateway.testOpenRouterConnection(),
  save: (payload) =>
    zaloIntegrationGateway.saveOpenRouterSettings(
      payload as OpenRouterUpdatePayload,
    ),
};

const CUSTOM_LLM_PANEL: ProviderPanelDescriptor = {
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

const JEV_PANEL: ProviderPanelDescriptor = {
  id: "jev",
  bundleKey: "jev",
  chrome: "standalone",
  title: "Jev (TypeSafe)",
  description:
    "Mô hình quyết định System One — phân loại ý định, hướng sắp xếp, và nhận diện lời xã giao cho bot. Bot vẫn hoạt động bình thường khi Jev tắt.",
  icon: <Brain className="size-4" />,
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

const PROVIDER_PANELS: readonly ProviderPanelDescriptor[] = [
  MINIMAX_PANEL,
  OPENROUTER_PANEL,
  CUSTOM_LLM_PANEL,
  JEV_PANEL,
];

const PROVIDER_PANELS_BY_ID: Record<ProviderPanelId, ProviderPanelDescriptor> =
  {
    minimax: MINIMAX_PANEL,
    openrouter: OPENROUTER_PANEL,
    "custom-llm": CUSTOM_LLM_PANEL,
    jev: JEV_PANEL,
  };

const PROVIDER_GROUP_IDS: Record<
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

const CHAIN_PANEL_ID_BY_PROVIDER: Record<LlmProvider, ProviderPanelId> = {
  minimax: "minimax",
  openrouter: "openrouter",
  custom: "custom-llm",
};

const PROVIDER_SETTINGS_BUNDLE_NULL: ProviderSettingsBundle = {
  minimax: null,
  openRouter: null,
  customLlm: null,
  jev: null,
};

/**
 * Per-field reset values for the provider form: secret fields clear (they are
 * masked), while text and select fields re-sync to their saved value so the
 * operator sees what is stored — an empty text input both hides the saved value
 * and invites browser autofill (a stray email), which then reads as a phantom
 * edit. Scoped to the given panels so a chain save never wipes an in-progress
 * Jev edit (and vice versa), matching the pre-refactor behavior.
 */
const resetProviderForm = (
  bundle: ProviderSettingsBundle,
  panels: readonly ProviderPanelDescriptor[] = PROVIDER_PANELS,
): ProviderFormState => {
  const form = emptyProviderForm();
  for (const descriptor of panels) {
    for (const field of descriptor.fields) {
      if (field.kind === "readonly") continue;
      form[field.formKey] = field.kind === "secret" ? "" : field.saved(bundle);
    }
  }
  return form;
};

// Canonical provider order. It seeds an operator who has never ranked the
// chain and completes a partial ranking; once a ranking exists, that ranking —
// not this array — decides who starts a turn and who takes over.
const LLM_PROVIDER_ORDER: readonly LlmProvider[] = [
  "minimax",
  "openrouter",
  "custom",
];

// Mirror of the backend normalizer: drop unknown names, dedupe, and append
// anything unranked in canonical order, so the stored ranking is always full.
const normalizeFailoverOrder = (order: LlmProvider[]): LlmProvider[] => {
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

type SettingsItemId =
  | "settings-zalo-channel"
  | "settings-facebook-messenger"
  | "settings-llm-providers"
  | "settings-jev"
  | "settings-agents"
  | "settings-users";

const FACEBOOK_OAUTH_CALLBACK_KEYS = [
  "facebook_oauth_status",
  "facebook_oauth_flow_id",
  "facebook_oauth_error",
] as const;

const resolveInitialSettingsItemId = (): SettingsItemId => {
  if (typeof window === "undefined") return "settings-zalo-channel";

  const queryIndex = window.location.hash.indexOf("?");
  if (queryIndex === -1) return "settings-zalo-channel";

  const params = new URLSearchParams(
    window.location.hash.slice(queryIndex + 1),
  );
  return FACEBOOK_OAUTH_CALLBACK_KEYS.some((key) => params.has(key))
    ? "settings-facebook-messenger"
    : "settings-zalo-channel";
};

type SettingsNavMode = "integrations" | "embedded";

type SettingsSectionNavItem = {
  itemId: SettingsItemId;
  label: string;
  description: string;
  Icon: LucideIcon;
  mode: SettingsNavMode;
};

const SETTINGS_NAV_ITEMS: SettingsSectionNavItem[] = [
  {
    itemId: "settings-zalo-channel",
    label: "Zalo",
    description: "Bot Platform và OA",
    Icon: MessageCircle,
    mode: "integrations",
  },
  {
    itemId: "settings-facebook-messenger",
    label: "Messenger",
    description: "Trang Facebook",
    Icon: MessagesSquare,
    mode: "integrations",
  },
  {
    itemId: "settings-llm-providers",
    label: "AI Providers",
    description: "Mặc định & dự phòng",
    Icon: Bot,
    mode: "integrations",
  },
  {
    itemId: "settings-jev",
    label: "Jev",
    description: "Mô hình quyết định",
    Icon: Brain,
    mode: "integrations",
  },
  {
    itemId: "settings-agents",
    label: "Agents",
    description: "Giọng trả lời",
    Icon: Workflow,
    mode: "embedded",
  },
  {
    itemId: "settings-users",
    label: "Người dùng",
    description: "Tài khoản & quyền",
    Icon: UsersRound,
    mode: "embedded",
  },
];

const SETTINGS_VIEW_COPY: Record<
  SettingsItemId,
  { kicker: string; title: string; description: string }
> = {
  "settings-zalo-channel": {
    kicker: "Kênh liên lạc",
    title: "Zalo",
    description: "Bot Platform và OA cho tin nhắn Zalo.",
  },
  "settings-facebook-messenger": {
    kicker: "Kênh liên lạc",
    title: "Messenger",
    description: "Kết nối Trang Facebook để nhắn tin với ứng viên.",
  },
  "settings-llm-providers": {
    kicker: "Nhà cung cấp AI",
    title: "AI Providers",
    description:
      "Chọn một nhà cung cấp mặc định. Khi hết quota, hệ thống tự chuyển sang nhà cung cấp còn lại theo thứ tự bên dưới.",
  },
  "settings-jev": {
    kicker: "Nhà cung cấp AI",
    title: "Jev",
    description: "Mô hình quyết định System One cho bot.",
  },
  "settings-agents": {
    kicker: "Không gian cài đặt",
    title: "Agents",
    description: "Giọng trả lời và adapter sử dụng.",
  },
  "settings-users": {
    kicker: "Không gian cài đặt",
    title: "Người dùng",
    description: "Tài khoản nội bộ và quyền quản trị.",
  },
};

const SecretInput = <K extends string>({
  id,
  label,
  status,
  statusState,
  value,
  placeholder,
  onChange,
  notify,
}: {
  id: K;
  label: string;
  status: SecretStatus;
  statusState?: SettingsStatusState;
  value: string;
  placeholder: string;
  onChange: (key: K, value: string) => void;
  notify: CredentialFieldNotify;
}) => (
  <CredentialSecretField
    id={id}
    label={label}
    status={status}
    statusState={statusState}
    value={value}
    placeholder={placeholder}
    onValueChange={(nextValue) => onChange(id, nextValue)}
    notify={notify}
  />
);

const ProviderSwitchField = ({
  id,
  label,
  checked,
  onCheckedChange,
  disabled = false,
}: {
  id: string;
  label: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
}) => (
  <div className="settings-switch-row">
    <div className="min-w-0">
      <Label htmlFor={id}>{label}</Label>
    </div>
    <Switch
      id={id}
      checked={checked}
      disabled={disabled}
      onCheckedChange={onCheckedChange}
    />
  </div>
);

const SettingsGroup = ({
  id,
  title,
  description,
  icon,
  meta,
  children,
  className = "",
  defaultOpen = false,
}: {
  id?: string;
  title: string;
  description?: string;
  icon: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
  defaultOpen?: boolean;
}) => {
  const isMobile = useIsMobile();
  const header = (
    <div className="settings-group-header">
      <div className="settings-group-title-group">
        <div className="settings-group-icon">{icon}</div>
        <div className="min-w-0">
          <div data-slot="settings-group-title">{title}</div>
          {description ? (
            <p className="settings-group-description">{description}</p>
          ) : null}
        </div>
      </div>
      {meta ? <div className="settings-group-meta">{meta}</div> : null}
    </div>
  );

  if (isMobile) {
    return (
      <details
        className={`settings-group settings-mobile-group tt-collapse tt-collapse-arrow ${className}`}
        id={id}
        open={defaultOpen}
      >
        <summary className="settings-mobile-group-summary tt-collapse-title">
          {header}
        </summary>
        <div className="settings-group-content tt-collapse-content">
          {children}
        </div>
      </details>
    );
  }

  return (
    <section className={`settings-group ${className}`} id={id}>
      {header}
      <div className="settings-group-content">{children}</div>
    </section>
  );
};

const SettingsSectionPanel = ({
  id,
  children,
}: {
  id: string;
  children: ReactNode;
}) => (
  <section className="settings-section-panel" id={id}>
    {children}
  </section>
);

const SettingsNavLinkContent = ({
  label,
  description,
  Icon,
}: {
  label: string;
  description: string;
  Icon: LucideIcon;
}) => (
  <>
    <span className="settings-side-nav-icon">
      <Icon className="size-4" />
    </span>
    <span className="settings-side-nav-copy">
      <strong>{label}</strong>
      <span>{description}</span>
    </span>
  </>
);

const SettingsSideNav = ({
  activeItemId,
  onItemSelect,
}: {
  activeItemId: SettingsItemId;
  onItemSelect: (itemId: SettingsItemId) => void;
}) => (
  <aside className="settings-side-nav" aria-label="Nhóm cài đặt">
    <div className="settings-side-nav-group">
      <span className="settings-side-nav-group-label">Mục cài đặt</span>
      <nav className="settings-side-nav-list">
        {SETTINGS_NAV_ITEMS.map((item) => {
          const active = item.itemId === activeItemId;

          return (
            <button
              key={item.label}
              type="button"
              className={`settings-side-nav-link${active ? " is-active" : ""}`}
              onClick={() => onItemSelect(item.itemId)}
            >
              <SettingsNavLinkContent
                label={item.label}
                description={item.description}
                Icon={item.Icon}
              />
            </button>
          );
        })}
      </nav>
    </div>
  </aside>
);

const MobileSettingsNav = ({
  activeItemId,
  onItemSelect,
}: {
  activeItemId: SettingsItemId;
  onItemSelect: (itemId: SettingsItemId) => void;
}) => {
  const activeItem =
    SETTINGS_NAV_ITEMS.find((item) => item.itemId === activeItemId) ??
    SETTINGS_NAV_ITEMS[0];

  return (
    <div className="settings-mobile-topbar">
      <Sheet>
        <SheetTrigger asChild>
          <Button
            type="button"
            variant="outline"
            className="settings-mobile-drawer-trigger"
            aria-label="Mở danh mục cài đặt"
          >
            <Menu className="size-5" aria-hidden="true" />
            <span className="min-w-0 flex-1 text-left">
              <span className="settings-mobile-drawer-label">Cài đặt</span>
              <span className="settings-mobile-drawer-current">
                {activeItem.label}
              </span>
            </span>
            <ChevronDown className="size-4" aria-hidden="true" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="settings-mobile-drawer">
          <SheetTitle className="settings-mobile-drawer-title">
            Cài đặt
          </SheetTitle>
          <p className="settings-mobile-drawer-description">
            Chọn khu vực bạn muốn cấu hình.
          </p>
          <nav className="settings-mobile-drawer-list" aria-label="Mục cài đặt">
            {SETTINGS_NAV_ITEMS.map((item) => {
              const active = item.itemId === activeItemId;

              return (
                <SheetClose asChild key={item.itemId}>
                  <button
                    type="button"
                    className={`settings-mobile-drawer-item${active ? " is-active" : ""}`}
                    onClick={() => onItemSelect(item.itemId)}
                  >
                    <SettingsNavLinkContent
                      label={item.label}
                      description={item.description}
                      Icon={item.Icon}
                    />
                  </button>
                </SheetClose>
              );
            })}
          </nav>
        </SheetContent>
      </Sheet>
    </div>
  );
};

const formatRelativeEpoch = (epoch: number | null): string => {
  if (!epoch) return "";
  const diffSeconds = Math.max(0, Math.round(Date.now() / 1000 - epoch));
  if (diffSeconds < 60) return "vừa xong";
  if (diffSeconds < 3600) return `${Math.floor(diffSeconds / 60)} phút trước`;
  if (diffSeconds < 86400) return `${Math.floor(diffSeconds / 3600)} giờ trước`;
  return `${Math.floor(diffSeconds / 86400)} ngày trước`;
};

// Provider probes surface upstream transport errors verbatim (HTTP status plus
// a raw JSON body). An operator console should state the consequence, not the
// wire format; the untouched text stays available as the element's tooltip.
const describeProviderTestError = (raw: string): string => {
  const text = raw.trim();
  if (!text) return "Kiểm tra thất bại";
  if (/\b429\b|rate.?limit|quota/i.test(text)) return "Hết hạn mức (429)";
  if (/\b401\b|\b403\b|unauthor|invalid.?api.?key|forbidden/i.test(text)) {
    return "Token bị từ chối (401)";
  }
  if (/\b404\b|not.?found|unknown.?model/i.test(text)) {
    return "Sai model hoặc Base URL (404)";
  }
  if (/timeout|timed.?out|ETIMEDOUT|ECONNRESET/i.test(text)) {
    return "Hết thời gian chờ";
  }
  if (/\b5\d{2}\b|internal.?server/i.test(text)) {
    return "Lỗi phía nhà cung cấp";
  }
  if (/ENOTFOUND|ECONNREFUSED|getaddrinfo|network/i.test(text)) {
    return "Không kết nối được";
  }
  // Unrecognised failure: keep the operator's own words, minus any JSON tail.
  const headline = text.split(/[:{]/)[0].trim();
  return headline.length > 0 && headline.length <= 80 ? headline : text;
};

const describeOaSignatureHealth = (health: ZaloOaSignatureHealth | null) => {
  if (!health || !health.last_status) {
    return {
      message:
        "Chưa có sự kiện webhook thực nào — trạng thái chữ ký sẽ cập nhật khi Zalo gửi tin nhắn đầu tiên.",
      type: "info" as const,
    };
  }
  if (health.last_status === "verified") {
    return {
      message: `Chữ ký webhook hợp lệ — cập nhật ${formatRelativeEpoch(health.last_ts)}.`,
      type: "success" as const,
    };
  }
  return {
    message: `Chữ ký webhook bị từ chối — Webhook Secret có thể sai${health.consec_failures ? ` (×${health.consec_failures})` : ""}. Cập nhật ${formatRelativeEpoch(health.last_mismatch_ts ?? health.last_ts)}.`,
    type: "warning" as const,
  };
};

export const ZaloIntegrationPage = () => {
  const translate = useTranslate();
  const notify = useNotify();
  const { permissions, isPending: permissionsPending } = usePermissions();
  const isMobile = useIsMobile();
  const [settings, setSettings] = useState<ZaloSettings | null>(null);
  const [providerSettings, setProviderSettings] =
    useState<ProviderSettingsBundle>(PROVIDER_SETTINGS_BUNDLE_NULL);
  const [settingsStatusState, setSettingsStatusState] =
    useState<SettingsStatusState>("loading");
  const [form, setForm] = useState<FormState>(emptyForm);
  const [providerForm, setProviderForm] =
    useState<ProviderFormState>(emptyProviderForm());
  const [providerEnabled, setProviderEnabled] = useState<
    Record<ProviderPanelId, boolean>
  >({ minimax: true, openrouter: false, "custom-llm": false, jev: false });
  const [providerTesting, setProviderTesting] = useState<
    Record<ProviderPanelId, boolean>
  >({ minimax: false, openrouter: false, "custom-llm": false, jev: false });
  const [providerSaving, setProviderSaving] = useState<
    Record<ProviderPanelGroup, boolean>
  >({ chain: false, standalone: false });
  const [providerLastTests, setProviderLastTests] = useState<
    Partial<Record<ProviderPanelId, ProviderTestStatus>>
  >({});
  const [llmDefaultProvider, setLlmDefaultProvider] =
    useState<LlmProvider>("minimax");
  const [llmFailoverOrder, setLlmFailoverOrder] = useState<LlmProvider[]>([
    ...LLM_PROVIDER_ORDER,
  ]);
  const [activeItemId, setActiveItemId] = useState<SettingsItemId>(
    resolveInitialSettingsItemId,
  );
  const [testingBot, setTestingBot] = useState(false);
  const [testingOa, setTestingOa] = useState(false);
  const handleCopy = useCallback(
    (label: string, value: string) =>
      copyCredentialFieldValue(label, value, notify as CredentialFieldNotify),
    [notify],
  );

  const load = useCallback(async () => {
    setSettingsStatusState("loading");
    try {
      const {
        zalo: data,
        minimax: minimaxData,
        openRouter: openRouterData,
        customLlm: customLlmData,
        jev: jevData,
      } = await zaloIntegrationGateway.loadSettingsBundle();
      setSettings(data);
      const loadedBundle: ProviderSettingsBundle = {
        minimax: minimaxData,
        openRouter: openRouterData,
        customLlm: customLlmData,
        jev: jevData,
      };
      setProviderSettings(loadedBundle);
      setForm((current) => ({
        ...current,
        zalo_oa_app_id: data.zalo_oa_app_id.value ?? "",
      }));
      const nextEnabled: Record<ProviderPanelId, boolean> = {
        minimax: true,
        openrouter: false,
        "custom-llm": false,
        jev: false,
      };
      const nextLastTests: Partial<
        Record<ProviderPanelId, ProviderTestStatus>
      > = {};
      for (const descriptor of PROVIDER_PANELS) {
        const saved = descriptor.readEnabled(loadedBundle);
        if (saved !== null) nextEnabled[descriptor.id] = saved;
        const lastTest = descriptor.initialTest(loadedBundle);
        if (lastTest) nextLastTests[descriptor.id] = lastTest;
      }
      setProviderEnabled(nextEnabled);
      setProviderLastTests(nextLastTests);
      setLlmDefaultProvider(customLlmData.llm_default_provider);
      setLlmFailoverOrder(
        normalizeFailoverOrder(customLlmData.llm_failover_order),
      );
      setProviderForm(resetProviderForm(loadedBundle));
      setSettingsStatusState("ready");
    } catch {
      setSettingsStatusState("error");
      notify("Không thể tải cấu hình tích hợp.", { type: "error" });
    }
  }, [notify]);

  useEffect(() => {
    if (!permissionsPending && permissions === "admin") {
      void load();
    }
  }, [load, permissions, permissionsPending]);

  const changedPayload = useMemo(() => {
    return buildZaloUpdatePayload(form, settings?.zalo_oa_app_id.value);
  }, [form, settings]);

  // ---------------------------------------------------------------------------
  // ProviderSettingsPanel: ONE dirty-check/save/probe/status implementation
  // for all descriptor-driven providers (minimax, openrouter, custom-llm, jev).
  // ---------------------------------------------------------------------------

  // Panel-global LLM-chain context the descriptors read and sync; identity
  // changes every render, which is fine — the shared helpers are plain
  // per-render closures like the rest of the page's handlers.
  const llmContext: ProviderLlmContext = {
    defaultProvider: llmDefaultProvider,
    failoverOrder: llmFailoverOrder,
    setDefaultProvider: setLlmDefaultProvider,
    setFailoverOrder: setLlmFailoverOrder,
  };

  // One dirty-check builder for every provider: secrets go out when non-empty,
  // text/select fields when they differ from their saved value, the enable
  // switch when it differs from the saved flag, plus any panel-global keys the
  // descriptor adds (default provider, failover order).
  const providerPayload = (id: ProviderPanelId): ProviderPayload => {
    const descriptor = PROVIDER_PANELS_BY_ID[id];
    const bundle = providerSettings;
    const savedEnabled = descriptor.readEnabled(bundle);
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
      if (!raw || raw === field.saved(bundle)) continue;
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
      Object.assign(payload, descriptor.extraPayload(llmContext, bundle));
    }
    return payload;
  };

  const hasProviderPanelEdits = (group: ProviderPanelGroup): boolean =>
    PROVIDER_GROUP_IDS[group].some(
      (id) => Object.keys(providerPayload(id)).length > 0,
    );

  const saveProviderPanels = async (group: ProviderPanelGroup) => {
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
    setProviderSaving((current) => ({ ...current, [group]: true }));
    try {
      let bundle = providerSettings;
      for (const descriptor of descriptors) {
        const payload = providerPayload(descriptor.id);
        if (Object.keys(payload).length === 0) continue;
        const saved = await descriptor.save(payload);
        bundle = {
          ...bundle,
          [descriptor.bundleKey]: saved,
        } as ProviderSettingsBundle;
        descriptor.afterSaveSync?.(bundle, llmContext);
      }
      setProviderSettings(bundle);
      const nextEnabled = { ...providerEnabled };
      for (const descriptor of descriptors) {
        const savedEnabled = descriptor.readEnabled(bundle);
        if (savedEnabled !== null) nextEnabled[descriptor.id] = savedEnabled;
      }
      setProviderEnabled(nextEnabled);
      setProviderForm(resetProviderForm(bundle, descriptors));
      notify("Đã lưu thay đổi", { type: "success" });
    } catch {
      notify("Không lưu được thay đổi.", { type: "error" });
    } finally {
      setProviderSaving((current) => ({ ...current, [group]: false }));
    }
  };

  const discardProviderPanels = (group: ProviderPanelGroup) => {
    const bundle = providerSettings;
    const nextEnabled = { ...providerEnabled };
    for (const descriptor of PROVIDER_GROUP_IDS[group].map(
      (id) => PROVIDER_PANELS_BY_ID[id],
    )) {
      const savedEnabled = descriptor.readEnabled(bundle);
      if (savedEnabled !== null) nextEnabled[descriptor.id] = savedEnabled;
      descriptor.discardSync?.(bundle, llmContext);
    }
    setProviderEnabled(nextEnabled);
    setProviderForm(
      resetProviderForm(
        bundle,
        PROVIDER_GROUP_IDS[group].map((id) => PROVIDER_PANELS_BY_ID[id]),
      ),
    );
  };

  const testProviderPanel = async (id: ProviderPanelId) => {
    const descriptor = PROVIDER_PANELS_BY_ID[id];
    setProviderTesting((current) => ({ ...current, [id]: true }));
    try {
      // Probe, never write: testing must not persist an untested credential.
      const result = await descriptor.testConnection(
        descriptor.buildTestBody?.(providerForm),
      );
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
    } finally {
      setProviderTesting((current) => ({ ...current, [id]: false }));
    }
  };

  const setValue = (key: keyof FormState, value: string) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const setProviderFormValue = (
    key: keyof ProviderFormState,
    value: string,
  ) => {
    setProviderForm((current) => ({ ...current, [key]: value }));
  };

  const chainProviderEnabled = (provider: LlmProvider): boolean => {
    if (provider === "minimax") return providerEnabled.minimax;
    if (provider === "openrouter") return providerEnabled.openrouter;
    return providerEnabled["custom-llm"];
  };

  const handleProviderEnabledChange = (
    provider: LlmProvider,
    checked: boolean,
  ) => {
    setProviderEnabled((current) => ({
      ...current,
      [CHAIN_PANEL_ID_BY_PROVIDER[provider]]: checked,
    }));

    // Walk the operator's ranked chain, not the canonical array: the panel
    // advertises that ranking as who takes over, and the backend chain builder
    // ranks by the same stored order. Picking canonically here would hand the
    // turn to a provider the operator deliberately ranked last.
    const otherEnabled = normalizeFailoverOrder(llmFailoverOrder).filter(
      (candidate) => candidate !== provider && chainProviderEnabled(candidate),
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

  const saveZaloChanges = async (scope: ZaloSettingsScope = "all") => {
    const payload =
      scope === "all"
        ? changedPayload
        : buildZaloUpdatePayload(form, settings?.zalo_oa_app_id.value, scope);
    if (Object.keys(payload).length === 0) return settings;

    const nextZalo = await zaloIntegrationGateway.saveZaloSettings(payload);
    setSettings(nextZalo);
    setForm({
      ...emptyForm,
      zalo_oa_app_id: nextZalo.zalo_oa_app_id.value ?? "",
    });
    return nextZalo;
  };

  const hasProviderEdits = hasProviderPanelEdits("chain");
  const hasJevEdits = hasProviderPanelEdits("standalone");

  const testChannel = async (
    request: () => Promise<ZaloChannelTestResult>,
    label: string,
    busySetter: (busy: boolean) => void,
    scope: Exclude<ZaloSettingsScope, "all">,
  ) => {
    busySetter(true);
    try {
      await saveZaloChanges(scope);
      const result = await request();
      if (result.connected) {
        // Show OA-specific warnings even when connected (e.g. secret key
        // invalid but access token still works — will break on next refresh).
        const warnings: string[] = [];
        if (result.oa_secret_valid === false) {
          warnings.push(
            "⚠️ Secret Key không hợp lệ — sẽ lỗi khi làm mới token",
          );
        }
        if (warnings.length > 0) {
          notify(`Kết nối ${label} thành công, nhưng: ${warnings.join("; ")}`, {
            type: "warning",
          });
        } else {
          notify(`Kết nối ${label} thành công`, { type: "success" });
        }
        return;
      }
      if (result.missing.length > 0) {
        const missing = result.missing
          .map((key) => ZALO_TEST_FIELD_LABELS[key] ?? key)
          .join(", ");
        notify(`Thiếu cấu hình: ${missing}`, { type: "warning" });
        return;
      }
      // Show the most specific error from the new diagnostics
      if (result.oa_secret_valid === false) {
        notify(
          "❌ Secret Key không hợp lệ! Lấy từ Zalo OA dashboard → Cài đặt → API",
          { type: "error" },
        );
        return;
      }
      if (result.oa_refresh_ok === false && result.oa_token_expired) {
        notify(
          "❌ Token hết hạn và không thể làm mới. Kiểm tra Secret Key và Refresh Token",
          { type: "error" },
        );
        return;
      }
      notify(result.errors.join("; ") || `Không kết nối được ${label}`, {
        type: "warning",
      });
    } finally {
      busySetter(false);
    }
  };

  const testBotConnection = () =>
    testChannel(
      zaloIntegrationGateway.testBotConnection,
      "Zalo Chatbot",
      setTestingBot,
      "bot",
    );

  const testOaConnection = () =>
    testChannel(
      zaloIntegrationGateway.testOaConnection,
      "Zalo OA",
      setTestingOa,
      "oa",
    );

  const activeItem =
    SETTINGS_NAV_ITEMS.find((item) => item.itemId === activeItemId) ??
    SETTINGS_NAV_ITEMS[0];
  const headerCopy = SETTINGS_VIEW_COPY[activeItem.itemId];
  const webhookHealth = describeOaSignatureHealth(
    settings?.zalo_oa_webhook_signature ?? null,
  );
  const botConfigured = [
    settings?.zalo_bot_token.configured,
    settings?.zalo_bot_webhook_secret.configured,
  ].filter(Boolean).length;
  const oaConfigured = [
    settings?.zalo_oa_app_id.configured,
    settings?.zalo_oa_secret_key.configured,
    settings?.zalo_oa_access_token.configured,
    settings?.zalo_oa_refresh_token.configured,
  ].filter(Boolean).length;
  const selectSettingsItem = (itemId: SettingsItemId) => {
    setActiveItemId(itemId);
  };

  useEffect(() => {
    const animationFrame = window.requestAnimationFrame(() => {
      document
        .querySelector<HTMLElement>(".settings-center-panel")
        ?.scrollTo({ top: 0, behavior: "auto" });
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [activeItem.itemId]);

  const renderInWorkspace = (content: ReactNode) => {
    if (isMobile) return content;

    return (
      <div className="inbox-bg-container settings-workspace">
        <div className="app settings-app" id="app">
          <section className="panel center-panel settings-center-panel">
            {content}
          </section>
        </div>
      </div>
    );
  };

  // One renderer for every descriptor field kind across chain and standalone
  // provider cards; zalo keeps its hand-built panel (channel tests, webhook
  // health, and the plain App ID field with copy button are channel-specific).
  const renderProviderField = (field: ProviderFieldDescriptor) => {
    if (field.kind === "readonly") {
      return (
        <div className="settings-field" key={field.label}>
          <div className="settings-field-label-row">
            <span className="settings-llm-field-label">{field.label}</span>
            {field.note ? (
              <span className="settings-llm-field-note">{field.note}</span>
            ) : null}
          </div>
          <p className="settings-llm-readonly-value">
            {field.value(providerSettings)}
          </p>
        </div>
      );
    }
    if (field.kind === "select") {
      return (
        <div className="settings-field" key={field.formKey}>
          <Label htmlFor={field.formKey}>{field.label}</Label>
          <Select
            value={providerForm[field.formKey]}
            onValueChange={(value) =>
              setProviderFormValue(field.formKey, value)
            }
          >
            <SelectTrigger id={field.formKey} className="settings-input">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {field.options.map((model) => (
                <SelectItem key={model} value={model}>
                  {model}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      );
    }
    if (field.kind === "text") {
      return (
        <div className="settings-field" key={field.formKey}>
          <Label htmlFor={field.formKey}>{field.label}</Label>
          <Input
            id={field.formKey}
            className="settings-input"
            autoComplete="off"
            value={providerForm[field.formKey]}
            placeholder={field.placeholder(providerSettings)}
            onChange={(event) =>
              setProviderFormValue(field.formKey, event.target.value)
            }
          />
        </div>
      );
    }
    return (
      <SecretInput
        key={field.formKey}
        id={field.formKey}
        label={field.label}
        placeholder={field.placeholder}
        status={field.status(providerSettings)}
        statusState={settingsStatusState}
        value={providerForm[field.formKey]}
        onChange={setProviderFormValue}
        notify={notify as CredentialFieldNotify}
      />
    );
  };

  const renderSettingsBody = () => {
    if (activeItemId === "settings-agents") {
      return (
        <section className="settings-embedded-resource">
          <PersonaList embedded />
        </section>
      );
    }

    if (activeItemId === "settings-users") {
      return (
        <section className="settings-embedded-resource settings-embedded-users">
          <UserList embedded />
        </section>
      );
    }

    if (activeItemId === "settings-facebook-messenger") {
      return <FacebookMessengerIntegrationPage />;
    }

    if (activeItemId === "settings-zalo-channel") {
      return (
        <SettingsSectionPanel id="settings-zalo-channel">
          <div className="settings-grid settings-grid-zalo">
            <SettingsGroup
              title="Zalo Chatbot"
              icon={<PlugZap className="size-4" />}
              meta={
                <SettingsGroupStatus
                  configured={botConfigured}
                  total={2}
                  state={settingsStatusState}
                />
              }
              defaultOpen
            >
              <SecretInput
                id="zalo_bot_token"
                label="Bot Token"
                placeholder="Nhập giá trị"
                status={settings?.zalo_bot_token ?? { configured: false }}
                statusState={settingsStatusState}
                value={form.zalo_bot_token}
                onChange={setValue}
                notify={notify as CredentialFieldNotify}
              />
              <SecretInput
                id="zalo_bot_webhook_secret"
                label="Bot Secret"
                placeholder="Nhập giá trị"
                status={
                  settings?.zalo_bot_webhook_secret ?? {
                    configured: false,
                  }
                }
                statusState={settingsStatusState}
                value={form.zalo_bot_webhook_secret}
                onChange={setValue}
                notify={notify as CredentialFieldNotify}
              />
              <div className="settings-oa-actions">
                <Button
                  type="button"
                  className="settings-test-button settings-primary-action tt-btn-touch"
                  onClick={testBotConnection}
                  disabled={testingBot || !settings}
                  aria-busy={testingBot}
                >
                  <Wifi className="size-4" />
                  {testingBot ? "Đang kiểm tra" : "Lưu & kiểm tra"}
                </Button>
              </div>
            </SettingsGroup>

            <SettingsGroup
              title="Zalo OA"
              icon={<MessageCircle className="size-4" />}
              meta={
                <SettingsGroupStatus
                  configured={oaConfigured}
                  total={4}
                  state={settingsStatusState}
                />
              }
            >
              <div className="settings-oa-fields">
                <div className="settings-field settings-field-has-action">
                  <div className="settings-field-label-row">
                    <Label htmlFor="zalo_oa_app_id">Zalo App ID</Label>
                    <SettingsFieldStatus
                      configured={settings?.zalo_oa_app_id.configured ?? false}
                      state={settingsStatusState}
                    />
                  </div>
                  <Input
                    id="zalo_oa_app_id"
                    value={form.zalo_oa_app_id}
                    className="settings-input"
                    onChange={(event) =>
                      setValue("zalo_oa_app_id", event.target.value)
                    }
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="settings-copy-app-id settings-input-action"
                    aria-label="Sao chép Zalo App ID"
                    disabled={!form.zalo_oa_app_id}
                    onClick={() =>
                      void handleCopy("Zalo App ID", form.zalo_oa_app_id)
                    }
                  >
                    <Copy />
                  </Button>
                </div>

                <SecretInput
                  id="zalo_oa_secret_key"
                  label="Bot Secret"
                  placeholder="Nhập giá trị"
                  status={settings?.zalo_oa_secret_key ?? { configured: false }}
                  statusState={settingsStatusState}
                  value={form.zalo_oa_secret_key}
                  onChange={setValue}
                  notify={notify as CredentialFieldNotify}
                />
                <SecretInput
                  id="zalo_oa_access_token"
                  label="OA Access Token"
                  placeholder="Nhập giá trị"
                  status={
                    settings?.zalo_oa_access_token ?? {
                      configured: false,
                    }
                  }
                  statusState={settingsStatusState}
                  value={form.zalo_oa_access_token}
                  onChange={setValue}
                  notify={notify as CredentialFieldNotify}
                />
                <SecretInput
                  id="zalo_oa_refresh_token"
                  label="OA Refresh Token"
                  placeholder="Nhập giá trị"
                  status={
                    settings?.zalo_oa_refresh_token ?? {
                      configured: false,
                    }
                  }
                  statusState={settingsStatusState}
                  value={form.zalo_oa_refresh_token}
                  onChange={setValue}
                  notify={notify as CredentialFieldNotify}
                />
                <div className="settings-oa-actions">
                  <Button
                    type="button"
                    className="settings-test-button settings-primary-action tt-btn-touch"
                    onClick={testOaConnection}
                    disabled={testingOa || !settings}
                    aria-busy={testingOa}
                  >
                    <Wifi className="size-4" />
                    {testingOa ? "Đang kiểm tra" : "Lưu & kiểm tra"}
                  </Button>
                </div>
                <details className="settings-advanced settings-webhook-health tt-collapse tt-collapse-arrow">
                  <summary className="settings-advanced-summary tt-collapse-title">
                    Webhook
                  </summary>
                  <p
                    className={`settings-webhook-message is-${webhookHealth.type}`}
                    role="status"
                  >
                    {webhookHealth.message}
                  </p>
                </details>
              </div>
            </SettingsGroup>
          </div>
        </SettingsSectionPanel>
      );
    }

    if (activeItemId === "settings-llm-providers") {
      // Failover order: the default starts every turn, the other providers
      // follow the operator-ranked spare order; disabled ones cannot serve.
      const chain: LlmProvider[] = [
        llmDefaultProvider,
        ...llmFailoverOrder.filter((p) => p !== llmDefaultProvider),
      ];
      const providerLabel: Record<LlmProvider, string> = {
        minimax: "MiniMax",
        openrouter: "OpenRouter",
        custom: "Xiaomi",
      };
      // Reorder within the displayed chain (default pinned at index 0 — it
      // always opens the turn); the stored ranking mirrors the displayed one.
      const moveProvider = (provider: LlmProvider, direction: -1 | 1) => {
        const index = chain.indexOf(provider);
        const target = index + direction;
        if (index < 1 || target < 1 || target >= chain.length) return;
        const next = [...chain];
        [next[index], next[target]] = [next[target], next[index]];
        setLlmFailoverOrder(next);
      };
      const enabledOf: Record<LlmProvider, boolean> = {
        minimax: providerEnabled.minimax,
        openrouter: providerEnabled.openrouter,
        custom: providerEnabled["custom-llm"],
      };
      // Only enabled providers can serve a turn, so the visible rank counts
      // them alone — a disabled card holds its slot but carries no number.
      const servingChain = chain.filter((provider) => enabledOf[provider]);
      const rankOf = (provider: LlmProvider): number | null => {
        const index = servingChain.indexOf(provider);
        return index === -1 ? null : index + 1;
      };
      const chipOf = (
        provider: LlmProvider,
      ): { label: string; cls: string } => {
        if (!enabledOf[provider]) return { label: "Tắt", cls: "is-muted" };
        const t = providerLastTests[CHAIN_PANEL_ID_BY_PROVIDER[provider]];
        if (t?.ok) return { label: "Sẵn sàng", cls: "is-success" };
        if (t && !t.ok) return { label: "Lỗi kiểm tra", cls: "is-danger" };
        return { label: "Chưa kiểm tra", cls: "is-muted" };
      };
      const testLineOf = (
        provider: LlmProvider,
      ): { text: string; title?: string; ok: boolean } => {
        const t = providerLastTests[CHAIN_PANEL_ID_BY_PROVIDER[provider]];
        if (!t) return { text: "Chưa kiểm tra", ok: true };
        if (t.ok) {
          return {
            text: `Kiểm tra ${formatRelativeEpoch(t.tested_at)} · ${t.latency_ms ?? "?"}ms`,
            ok: true,
          };
        }
        const raw = t.error || "";
        return { text: describeProviderTestError(raw), title: raw, ok: false };
      };
      // Card header: the failover rank replaces a decorative glyph, so the
      // card states its own position in the chain.
      const rankBadgeOf = (provider: LlmProvider) => {
        const rank = rankOf(provider);
        return (
          <span
            className={`settings-llm-rank${rank === 1 ? " is-default" : ""}${
              rank === null ? " is-off" : ""
            }`}
            aria-hidden="true"
          >
            {rank ?? "—"}
          </span>
        );
      };
      const cardMetaOf = (provider: LlmProvider) => {
        const index = chain.indexOf(provider);
        const movable = provider !== llmDefaultProvider;
        const chip = chipOf(provider);
        return (
          <>
            {movable ? (
              <span className="settings-llm-moves">
                <button
                  type="button"
                  className="settings-llm-move"
                  disabled={index <= 1}
                  onClick={() => moveProvider(provider, -1)}
                  aria-label={`Tăng ưu tiên cho ${providerLabel[provider]}`}
                >
                  <ChevronUp className="size-4" />
                </button>
                <button
                  type="button"
                  className="settings-llm-move"
                  disabled={index === chain.length - 1}
                  onClick={() => moveProvider(provider, 1)}
                  aria-label={`Giảm ưu tiên cho ${providerLabel[provider]}`}
                >
                  <ChevronDown className="size-4" />
                </button>
              </span>
            ) : null}
            <span className={`settings-llm-chip ${chip.cls}`}>
              {chip.label}
            </span>
          </>
        );
      };
      const roleRowOf = (provider: LlmProvider, switchId: string) => (
        <div className="settings-llm-role-row">
          <label className="settings-llm-radio">
            <input
              type="radio"
              name="llm_default_provider"
              checked={llmDefaultProvider === provider}
              disabled={!enabledOf[provider]}
              onChange={() => setLlmDefaultProvider(provider)}
            />
            <span>Chạy đầu tiên</span>
          </label>
          <ProviderSwitchField
            id={switchId}
            label="Kích hoạt"
            checked={enabledOf[provider]}
            onCheckedChange={(checked) =>
              handleProviderEnabledChange(provider, checked)
            }
          />
        </div>
      );
      const verifyRowOf = (provider: LlmProvider, ready: boolean) => {
        const line = testLineOf(provider);
        const panelId = CHAIN_PANEL_ID_BY_PROVIDER[provider];
        const anyChainTesting = PROVIDER_GROUP_IDS.chain.some(
          (id) => providerTesting[id],
        );
        return (
          <div className="settings-llm-verify">
            <span
              className={`settings-llm-testline${line.ok ? "" : " is-error"}`}
              title={line.title}
            >
              {line.text}
            </span>
            <Button
              type="button"
              variant="outline"
              className="tt-btn-touch"
              onClick={() => {
                void testProviderPanel(panelId);
              }}
              disabled={anyChainTesting || !ready}
              aria-busy={providerTesting[panelId]}
            >
              {providerTesting[panelId] ? "Đang kiểm tra" : "Kiểm tra"}
            </Button>
          </div>
        );
      };
      const disabledProviders = chain.filter(
        (provider) => !enabledOf[provider],
      );

      return (
        <SettingsSectionPanel id="settings-llm-providers">
          <p className="settings-llm-chain" data-slot="settings-llm-chain">
            <span className="settings-llm-chain-label">Thứ tự dự phòng</span>
            {servingChain.length === 0 ? (
              <span className="settings-llm-chain-empty">
                Chưa bật nhà cung cấp nào — bot không thể trả lời.
              </span>
            ) : (
              servingChain.map((provider, index) => (
                <Fragment key={provider}>
                  {index > 0 ? (
                    <span className="settings-llm-chain-arrow" aria-hidden>
                      →
                    </span>
                  ) : null}
                  <span
                    className={`settings-llm-chain-item is-on${
                      index === 0 ? " is-default" : ""
                    }`}
                  >
                    <em>{index + 1}</em>
                    {providerLabel[provider]}
                  </span>
                </Fragment>
              ))
            )}
            {disabledProviders.length > 0 ? (
              <span className="settings-llm-chain-off">
                Đang tắt:{" "}
                {disabledProviders
                  .map((provider) => providerLabel[provider])
                  .join(", ")}
              </span>
            ) : null}
          </p>

          <div className="settings-grid settings-grid-models">
            {/* Cards render in failover order, so the board itself is the
                ranking: position, rank badge, and reorder control agree. */}
            {chain.map((provider) => {
              const descriptor =
                PROVIDER_PANELS_BY_ID[CHAIN_PANEL_ID_BY_PROVIDER[provider]];
              const ready = descriptor.readEnabled(providerSettings) !== null;
              return (
                <SettingsGroup
                  key={provider}
                  className={`settings-llm-card${
                    enabledOf[provider] ? "" : " is-off"
                  }`}
                  title={providerLabel[provider]}
                  icon={rankBadgeOf(provider)}
                  meta={cardMetaOf(provider)}
                >
                  {roleRowOf(provider, descriptor.enableKey)}
                  {descriptor.fields.map((field) => renderProviderField(field))}
                  {verifyRowOf(provider, ready)}
                </SettingsGroup>
              );
            })}
          </div>

          <div
            className={`settings-llm-footer${
              hasProviderEdits ? " is-dirty" : ""
            }`}
          >
            <Button
              type="button"
              variant="ghost"
              className="tt-btn-touch"
              onClick={() => discardProviderPanels("chain")}
              disabled={!hasProviderEdits || providerSaving.chain}
            >
              Huỷ
            </Button>
            <Button
              type="button"
              className="settings-primary-action tt-btn-touch"
              onClick={() => {
                void saveProviderPanels("chain");
              }}
              disabled={!hasProviderEdits || providerSaving.chain}
            >
              {providerSaving.chain ? "Đang lưu" : "Lưu thay đổi"}
            </Button>
            <span className="settings-llm-footer-note">
              {hasProviderEdits
                ? "Có thay đổi chưa lưu."
                : "Token được mã hoá, không hiển thị lại."}
            </span>
          </div>
        </SettingsSectionPanel>
      );
    }

    if (activeItemId === "settings-jev") {
      const descriptor = PROVIDER_PANELS_BY_ID.jev;
      const ready = descriptor.readEnabled(providerSettings) !== null;
      const jevTestLine: { text: string; title?: string; ok: boolean } =
        providerLastTests.jev
          ? providerLastTests.jev.ok
            ? {
                text: `Kiểm tra ${formatRelativeEpoch(providerLastTests.jev.tested_at)} · ${providerLastTests.jev.latency_ms ?? "?"}ms`,
                ok: true,
              }
            : {
                text: describeProviderTestError(
                  providerLastTests.jev.error || "",
                ),
                title: providerLastTests.jev.error ?? undefined,
                ok: false,
              }
          : { text: "Chưa kiểm tra", ok: true };
      const jevStatus = descriptor.status?.(
        providerSettings,
        providerEnabled.jev,
      );

      return (
        <SettingsSectionPanel id="settings-jev">
          <div className="settings-grid settings-grid-models">
            <SettingsGroup
              className="settings-llm-card"
              title={descriptor.title}
              description={descriptor.description}
              icon={descriptor.icon}
              meta={
                jevStatus ? (
                  <SettingsGroupStatus
                    configured={jevStatus.configured}
                    total={jevStatus.total}
                    disabled={jevStatus.disabled}
                    state={settingsStatusState}
                  />
                ) : null
              }
            >
              <ProviderSwitchField
                id={descriptor.enableKey}
                label="Kích hoạt"
                checked={providerEnabled.jev}
                onCheckedChange={(checked) =>
                  setProviderEnabled((current) => ({
                    ...current,
                    jev: checked,
                  }))
                }
              />
              {descriptor.fields.map((field) => renderProviderField(field))}
              <div className="settings-llm-verify">
                <span
                  className={`settings-llm-testline${jevTestLine.ok ? "" : " is-error"}`}
                  title={jevTestLine.title}
                >
                  {jevTestLine.text}
                </span>
                <Button
                  type="button"
                  variant="outline"
                  className="tt-btn-touch"
                  onClick={() => {
                    void testProviderPanel("jev");
                  }}
                  disabled={providerTesting.jev || !ready}
                  aria-busy={providerTesting.jev}
                >
                  {providerTesting.jev ? "Đang kiểm tra" : "Kiểm tra"}
                </Button>
              </div>
            </SettingsGroup>
          </div>

          <div
            className={`settings-llm-footer${hasJevEdits ? " is-dirty" : ""}`}
          >
            <Button
              type="button"
              className="settings-primary-action tt-btn-touch"
              onClick={() => {
                void saveProviderPanels("standalone");
              }}
              disabled={!hasJevEdits || providerSaving.standalone}
            >
              {providerSaving.standalone ? "Đang lưu" : "Lưu thay đổi"}
            </Button>
            <span className="settings-llm-footer-note">
              {hasJevEdits
                ? "Có thay đổi chưa lưu."
                : "Token được mã hoá, không hiển thị lại."}
            </span>
          </div>
        </SettingsSectionPanel>
      );
    }
  };

  if (!permissionsPending && permissions !== "admin") {
    return renderInWorkspace(
      <div className="settings-workspace-content text-foreground">
        <div className="ops-page-shell settings-page-shell">
          <div className="ops-panel settings-access-denied">
            {translate("ra.auth.access_denied", { _: "Access denied" })}
          </div>
        </div>
      </div>,
    );
  }

  return renderInWorkspace(
    <div className="settings-workspace-content text-foreground">
      <div className="ops-page-shell settings-page-shell">
        <div className="settings-console">
          {isMobile ? (
            <MobileSettingsNav
              activeItemId={activeItemId}
              onItemSelect={selectSettingsItem}
            />
          ) : (
            <SettingsSideNav
              activeItemId={activeItemId}
              onItemSelect={selectSettingsItem}
            />
          )}

          <div className="settings-main">
            <header className="ops-command-header settings-command-header">
              <div className="ops-command-title">
                <div className="min-w-0">
                  <p className="ops-kicker">{headerCopy.kicker}</p>
                  <h1>{headerCopy.title}</h1>
                  <p>{headerCopy.description}</p>
                </div>
              </div>
            </header>

            {renderSettingsBody()}
          </div>
        </div>
      </div>
    </div>,
  );
};
