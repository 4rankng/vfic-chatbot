import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNotify, usePermissions, useTranslate } from "ra-core";
import {
  Bot,
  Cpu,
  MessageCircle,
  PlugZap,
  Save,
  Settings,
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
import { apiJson } from "../providers/rest/api";
import { InboxIcons } from "../conversations/InboxIcons";
import { useIsMobile } from "@/hooks/use-mobile";
import { PersonaList } from "../personas/PersonaList";
import { UserList } from "../users/UserList";
import "../conversations/inbox.css";
import "./settings.css";

type SecretStatus = { configured: boolean; preview?: string | null };
type PlainStatus = { configured: boolean; value?: string | null };

type ZaloOaSignatureHealth = {
  last_status: "verified" | "mismatched" | null;
  last_ts: number | null;
  last_mismatch_ts: number | null;
  consec_failures: number | null;
};

type ZaloOaSignatureVerifyResult = {
  verified: boolean;
  secret_configured: boolean;
  app_id_configured: boolean;
  matched_label: string | null;
  detail: string;
};

type ZaloSettings = {
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

type MinimaxSettings = {
  minimax_api_key: SecretStatus;
  minimax_base_url: string;
  minimax_agent_model: string;
  minimax_safety_model: string;
  minimax_enable: boolean;
  llm_default_provider: LlmProvider;
};

type OpenRouterSettings = {
  openrouter_api_key: SecretStatus;
  openrouter_base_url: string;
  openrouter_agent_model: string;
  openrouter_safety_model: string;
  openrouter_digest_model: string;
  openrouter_enable: boolean;
  llm_default_provider: LlmProvider;
};

type LlmProvider = "minimax" | "openrouter";

type FormState = {
  zalo_bot_token: string;
  zalo_bot_webhook_secret: string;
  zalo_oa_app_id: string;
  zalo_oa_secret_key: string;
  zalo_oa_access_token: string;
  zalo_oa_refresh_token: string;
};

type MinimaxFormState = {
  minimax_api_key: string;
};

type OpenRouterFormState = {
  openrouter_api_key: string;
};

type MinimaxUpdatePayload = {
  minimax_api_key?: string;
  minimax_enable?: boolean;
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

const emptyForm: FormState = {
  zalo_bot_token: "",
  zalo_bot_webhook_secret: "",
  zalo_oa_app_id: "",
  zalo_oa_secret_key: "",
  zalo_oa_access_token: "",
  zalo_oa_refresh_token: "",
};

type ZaloChannelTestResult = {
  configured: boolean;
  connected: boolean;
  missing: string[];
  errors: string[];
};

type IntegrationConfigTestResult = {
  configured: boolean;
  missing: string[];
};

const ZALO_TEST_FIELD_LABELS: Record<string, string> = {
  zalo_bot_token: "Bot Token",
  zalo_oa_app_id: "OA App ID",
  zalo_oa_secret_key: "OA Secret",
  zalo_oa_access_token: "OA Access Token",
  zalo_oa_refresh_token: "OA Refresh Token",
};

const INTEGRATION_TEST_FIELD_LABELS: Record<string, string> = {
  minimax_api_key: "Access Token",
  openrouter_api_key: "Access Token",
};

const emptyMinimaxForm: MinimaxFormState = {
  minimax_api_key: "",
};

const emptyOpenRouterForm: OpenRouterFormState = {
  openrouter_api_key: "",
};

const OPENROUTER_MODEL_OPTIONS = [
  "deepseek/deepseek-v4-flash",
  "deepseek/deepseek-chat",
  "deepseek/deepseek-r1",
];

type SettingsItemId =
  | "settings-zalo-channel"
  | "settings-minimax"
  | "settings-openrouter"
  | "settings-agents"
  | "settings-users";

type SettingsNavMode = "integrations" | "embedded";
type IntegrationSectionId =
  | "settings-zalo-channel"
  | "settings-minimax"
  | "settings-openrouter";
type SaveResult = "idle" | "success" | "error";

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
    itemId: "settings-minimax",
    label: "Minimax",
    description: "Model chính",
    Icon: Bot,
    mode: "integrations",
  },
  {
    itemId: "settings-openrouter",
    label: "OpenRouter",
    description: "Fallback và embeddings",
    Icon: Cpu,
    mode: "integrations",
  },
  {
    itemId: "settings-agents",
    label: "Agents",
    description: "Giọng trả lời theo dự án",
    Icon: Workflow,
    mode: "embedded",
  },
  {
    itemId: "settings-users",
    label: "Users",
    description: "Tài khoản quản trị",
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
    description: "Cấu hình Bot Platform và Official Account dùng để nhắn tin.",
  },
  "settings-minimax": {
    kicker: "Model chính",
    title: "Minimax",
    description: "Cấu hình khóa API cho model chính của Agent.",
  },
  "settings-openrouter": {
    kicker: "Model dự phòng",
    title: "OpenRouter",
    description: "Cấu hình fallback và embeddings khi cần chuyển tuyến model.",
  },
  "settings-agents": {
    kicker: "Không gian cài đặt",
    title: "Agents",
    description: "Quản lý giọng trả lời, prompt và phân công Agent theo dự án.",
  },
  "settings-users": {
    kicker: "Không gian cài đặt",
    title: "Users",
    description: "Quản lý tài khoản nội bộ và quyền truy cập quản trị.",
  },
};

const SecretInput = ({
  id,
  label,
  status,
  value,
  onChange,
}: {
  id: keyof FormState;
  label: string;
  status: SecretStatus;
  value: string;
  onChange: (key: keyof FormState, value: string) => void;
}) => (
  <div className="settings-field">
    <div className="flex items-center justify-between gap-3">
      <Label htmlFor={id}>{label}</Label>
    </div>
    <Input
      id={id}
      type="password"
      autoComplete="off"
      value={value}
      placeholder={
        status.preview ? `Hiện tại: ${status.preview}` : "Nhập giá trị"
      }
      className="settings-input"
      onChange={(event) => onChange(id, event.target.value)}
    />
  </div>
);

const MinimaxSecretInput = ({
  id,
  label,
  status,
  value,
  onChange,
}: {
  id: keyof MinimaxFormState;
  label: string;
  status: SecretStatus;
  value: string;
  onChange: (key: keyof MinimaxFormState, value: string) => void;
}) => (
  <div className="settings-field">
    <div className="flex items-center justify-between gap-3">
      <Label htmlFor={id}>{label}</Label>
    </div>
    <Input
      id={id}
      type="password"
      autoComplete="off"
      value={value}
      placeholder={
        status.preview ? `Hiện tại: ${status.preview}` : "Dán token Minimax"
      }
      className="settings-input"
      onChange={(event) => onChange(id, event.target.value)}
    />
  </div>
);

const OpenRouterSecretInput = ({
  id,
  label,
  status,
  value,
  onChange,
}: {
  id: keyof OpenRouterFormState;
  label: string;
  status: SecretStatus;
  value: string;
  onChange: (key: keyof OpenRouterFormState, value: string) => void;
}) => (
  <div className="settings-field">
    <div className="flex items-center justify-between gap-3">
      <Label htmlFor={id}>{label}</Label>
    </div>
    <Input
      id={id}
      type="password"
      autoComplete="off"
      value={value}
      placeholder={
        status.preview ? `Hiện tại: ${status.preview}` : "Dán token OpenRouter"
      }
      className="settings-input"
      onChange={(event) => onChange(id, event.target.value)}
    />
  </div>
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

const DefaultProviderSwitch = ({
  provider,
  enabled,
  checked,
  otherEnabled,
  onCheckedChange,
}: {
  provider: LlmProvider;
  enabled: boolean;
  checked: boolean;
  otherEnabled: boolean;
  onCheckedChange: (provider: LlmProvider, checked: boolean) => void;
}) => (
  <ProviderSwitchField
    id={`llm_default_provider_${provider}`}
    label="Mặc định"
    checked={checked}
    disabled={!enabled || (checked && !otherEnabled)}
    onCheckedChange={(next) => onCheckedChange(provider, next)}
  />
);

const SettingsCard = ({
  id,
  title,
  description,
  icon,
  meta,
  children,
  className = "",
}: {
  id?: string;
  title: string;
  description?: string;
  icon: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
}) => (
  <section className={`settings-card ${className}`} id={id}>
    <div className="settings-card-header">
      <div className="settings-card-title-group">
        <div className="settings-card-icon">{icon}</div>
        <div className="min-w-0">
          <div data-slot="card-title">{title}</div>
          {description ? (
            <p className="settings-card-description">{description}</p>
          ) : null}
        </div>
      </div>
      {meta ? <div className="settings-card-meta">{meta}</div> : null}
    </div>
    <div className="settings-card-content">{children}</div>
  </section>
);

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

const scrollToSettingsSection = (sectionId: string) => {
  const section = document.getElementById(sectionId);
  if (!section) return;

  const prefersReducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  ).matches;

  section.scrollIntoView({
    behavior: prefersReducedMotion ? "auto" : "smooth",
    block: "start",
  });
};

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

const formatRelativeEpoch = (epoch: number | null): string => {
  if (!epoch) return "";
  const diffSeconds = Math.max(0, Math.round(Date.now() / 1000 - epoch));
  if (diffSeconds < 60) return "vừa xong";
  if (diffSeconds < 3600) return `${Math.floor(diffSeconds / 60)} phút trước`;
  if (diffSeconds < 86400) return `${Math.floor(diffSeconds / 3600)} giờ trước`;
  return `${Math.floor(diffSeconds / 86400)} ngày trước`;
};

const ZaloOaSignatureHealthBadge = ({
  health,
}: {
  health: ZaloOaSignatureHealth | null;
}) => {
  if (!health || !health.last_status) {
    return (
      <p className="text-sm text-muted-foreground">
        Chưa có sự kiện webhook thực nào — trạng thái chữ ký sẽ cập nhật khi
        Zalo gửi tin nhắn đầu tiên.
      </p>
    );
  }
  if (health.last_status === "verified") {
    return (
      <p className="text-sm font-medium text-emerald-600">
        ✅ Chữ ký webhook hợp lệ — cập nhật{" "}
        {formatRelativeEpoch(health.last_ts)}.
      </p>
    );
  }
  return (
    <p className="text-sm font-medium text-red-600">
      ❌ Chữ ký webhook bị từ chối — OA Secret Key có thể sai
      {health.consec_failures ? ` (×${health.consec_failures})` : ""}. Cập nhật{" "}
      {formatRelativeEpoch(health.last_mismatch_ts ?? health.last_ts)}.
    </p>
  );
};

const ZaloOaSignatureVerifyPanel = ({
  secretConfigured,
}: {
  secretConfigured: boolean;
}) => {
  const notify = useNotify();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [signature, setSignature] = useState("");
  const [rawBody, setRawBody] = useState("");
  const [timestamp, setTimestamp] = useState("");
  const [result, setResult] = useState<ZaloOaSignatureVerifyResult | null>(
    null,
  );

  const run = async () => {
    if (!signature.trim() || !rawBody) {
      notify("Dán chữ ký (X-ZEvent-Signature) và raw body từ sự kiện Zalo.", {
        type: "warning",
      });
      return;
    }
    setBusy(true);
    try {
      const out = await apiJson<ZaloOaSignatureVerifyResult>(
        "/api/v1/admin/integrations/zalo/oa/verify-signature",
        {
          method: "POST",
          body: {
            signature: signature.trim(),
            raw_body: rawBody,
            timestamp: timestamp.trim(),
          },
        },
      );
      setResult(out);
      notify(
        out.verified
          ? "Chữ ký khớp — OA Secret Key đúng."
          : "Chữ ký không khớp.",
        { type: out.verified ? "success" : "warning" },
      );
    } catch {
      setResult(null);
      notify("Không xác thực được chữ ký.", { type: "warning" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="settings-oa-verify">
      <button
        type="button"
        className="text-sm font-medium text-foreground hover:underline"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? "▾" : "▸"} Xác thực chữ ký từ sự kiện mẫu
      </button>
      {open ? (
        <div className="settings-oa-verify-body">
          <p className="text-xs text-muted-foreground">
            Dán một sự kiện thật từ Zalo (console test hoặc log máy chủ) để xác
            nhận OA Secret Key đã đúng. Body phải là nguyên văn byte-for-byte
            Zalo gửi.
          </p>
          <div className="settings-field">
            <Label htmlFor="oa-sig-signature">X-ZEvent-Signature</Label>
            <Input
              id="oa-sig-signature"
              className="settings-input"
              placeholder="mac=…"
              value={signature}
              onChange={(event) => setSignature(event.target.value)}
            />
          </div>
          <div className="settings-field">
            <Label htmlFor="oa-sig-body">Raw body (nguyên văn)</Label>
            <textarea
              id="oa-sig-body"
              className="settings-input font-mono text-xs"
              rows={5}
              placeholder='{"app_id":"…","event_name":"user_send_text",…}'
              value={rawBody}
              onChange={(event) => setRawBody(event.target.value)}
            />
          </div>
          <div className="settings-field">
            <Label htmlFor="oa-sig-ts">X-ZEvent-Timestamp</Label>
            <Input
              id="oa-sig-ts"
              className="settings-input"
              placeholder="1783527327967"
              value={timestamp}
              onChange={(event) => setTimestamp(event.target.value)}
            />
          </div>
          <div className="settings-oa-actions">
            <Button
              type="button"
              variant="outline"
              className="settings-test-button"
              onClick={run}
              disabled={busy || !secretConfigured}
            >
              {busy ? "Đang xác thực" : "Xác thực"}
            </Button>
          </div>
          {result ? (
            <p
              className={
                result.verified
                  ? "text-sm font-medium text-emerald-600"
                  : "text-sm font-medium text-red-600"
              }
            >
              {result.verified ? "✅" : "❌"} {result.detail}
              {result.matched_label ? ` (${result.matched_label})` : ""}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};

export const ZaloIntegrationPage = () => {
  const translate = useTranslate();
  const notify = useNotify();
  const { permissions, isPending: permissionsPending } = usePermissions();
  const isMobile = useIsMobile();
  const [settings, setSettings] = useState<ZaloSettings | null>(null);
  const [minimaxSettings, setMinimaxSettings] =
    useState<MinimaxSettings | null>(null);
  const [openRouterSettings, setOpenRouterSettings] =
    useState<OpenRouterSettings | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [minimaxForm, setMinimaxForm] =
    useState<MinimaxFormState>(emptyMinimaxForm);
  const [openRouterForm, setOpenRouterForm] =
    useState<OpenRouterFormState>(emptyOpenRouterForm);
  const [minimaxEnabled, setMinimaxEnabled] = useState(true);
  const [openRouterEnabled, setOpenRouterEnabled] = useState(false);
  const [llmDefaultProvider, setLlmDefaultProvider] =
    useState<LlmProvider>("minimax");
  const [openRouterModel, setOpenRouterModel] = useState(
    "deepseek/deepseek-v4-flash",
  );
  const [activeItemId, setActiveItemId] = useState<SettingsItemId>(
    "settings-zalo-channel",
  );
  const [savingSection, setSavingSection] =
    useState<IntegrationSectionId | null>(null);
  const [saveResults, setSaveResults] = useState<
    Record<IntegrationSectionId, SaveResult>
  >({
    "settings-zalo-channel": "idle",
    "settings-minimax": "idle",
    "settings-openrouter": "idle",
  });
  const [testingBot, setTestingBot] = useState(false);
  const [testingOa, setTestingOa] = useState(false);
  const [testingMinimax, setTestingMinimax] = useState(false);
  const [testingOpenRouter, setTestingOpenRouter] = useState(false);

  const load = async () => {
    const [data, minimaxData, openRouterData] = await Promise.all([
      apiJson<ZaloSettings>("/api/v1/admin/integrations/zalo"),
      apiJson<MinimaxSettings>("/api/v1/admin/integrations/minimax"),
      apiJson<OpenRouterSettings>("/api/v1/admin/integrations/openrouter"),
    ]);
    setSettings(data);
    setMinimaxSettings(minimaxData);
    setOpenRouterSettings(openRouterData);
    setForm((current) => ({
      ...current,
      zalo_oa_app_id: data.zalo_oa_app_id.value ?? "",
    }));
    setMinimaxEnabled(minimaxData.minimax_enable);
    setOpenRouterEnabled(openRouterData.openrouter_enable);
    setLlmDefaultProvider(openRouterData.llm_default_provider);
    setOpenRouterModel(openRouterData.openrouter_agent_model);
    setMinimaxForm(emptyMinimaxForm);
    setOpenRouterForm(emptyOpenRouterForm);
  };

  useEffect(() => {
    if (!permissionsPending && permissions === "admin") {
      void load();
    }
  }, [permissions, permissionsPending]);

  const changedPayload = useMemo(() => {
    const payload: Partial<FormState> = {};
    for (const key of Object.keys(form) as (keyof FormState)[]) {
      const value = form[key].trim();
      if (!value) continue;
      if (
        key === "zalo_oa_app_id" &&
        value === settings?.zalo_oa_app_id.value
      ) {
        continue;
      }
      payload[key] = value;
    }
    return payload;
  }, [form, settings]);

  const changedMinimaxPayload = useMemo(() => {
    const payload: MinimaxUpdatePayload = {};
    const value = minimaxForm.minimax_api_key.trim();
    if (value) payload.minimax_api_key = value;
    if (minimaxSettings && minimaxEnabled !== minimaxSettings.minimax_enable) {
      payload.minimax_enable = minimaxEnabled;
    }
    if (
      activeItemId === "settings-minimax" &&
      minimaxSettings &&
      llmDefaultProvider !== minimaxSettings.llm_default_provider
    ) {
      payload.llm_default_provider = llmDefaultProvider;
    }
    return payload;
  }, [
    activeItemId,
    minimaxForm,
    minimaxEnabled,
    llmDefaultProvider,
    minimaxSettings,
  ]);

  const changedOpenRouterPayload = useMemo(() => {
    const payload: OpenRouterUpdatePayload = {};
    const value = openRouterForm.openrouter_api_key.trim();
    if (value) payload.openrouter_api_key = value;
    if (
      openRouterSettings &&
      openRouterEnabled !== openRouterSettings.openrouter_enable
    ) {
      payload.openrouter_enable = openRouterEnabled;
    }
    if (
      openRouterSettings &&
      openRouterModel.trim() &&
      openRouterModel.trim() !== openRouterSettings.openrouter_agent_model
    ) {
      payload.openrouter_agent_model = openRouterModel.trim();
      payload.openrouter_safety_model = openRouterModel.trim();
      payload.openrouter_digest_model = openRouterModel.trim();
    }
    if (
      activeItemId === "settings-openrouter" &&
      openRouterSettings &&
      llmDefaultProvider !== openRouterSettings.llm_default_provider
    ) {
      payload.llm_default_provider = llmDefaultProvider;
    }
    return payload;
  }, [
    activeItemId,
    openRouterForm,
    openRouterEnabled,
    openRouterModel,
    llmDefaultProvider,
    openRouterSettings,
  ]);

  const setValue = (key: keyof FormState, value: string) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const setMinimaxValue = (key: keyof MinimaxFormState, value: string) => {
    setMinimaxForm((current) => ({ ...current, [key]: value }));
  };

  const setOpenRouterValue = (
    key: keyof OpenRouterFormState,
    value: string,
  ) => {
    setOpenRouterForm((current) => ({ ...current, [key]: value }));
  };

  const chooseDefaultProvider = (provider: LlmProvider) => {
    if (provider === "minimax" && minimaxEnabled) {
      setLlmDefaultProvider("minimax");
      return;
    }
    if (provider === "openrouter" && openRouterEnabled) {
      setLlmDefaultProvider("openrouter");
    }
  };

  const toggleDefaultProvider = (provider: LlmProvider, checked: boolean) => {
    if (checked) {
      chooseDefaultProvider(provider);
      return;
    }
    chooseDefaultProvider(provider === "minimax" ? "openrouter" : "minimax");
  };

  const handleMinimaxEnabledChange = (checked: boolean) => {
    setMinimaxEnabled(checked);
    if (!checked && llmDefaultProvider === "minimax" && openRouterEnabled) {
      setLlmDefaultProvider("openrouter");
    }
    if (checked && !openRouterEnabled) {
      setLlmDefaultProvider("minimax");
    }
  };

  const handleOpenRouterEnabledChange = (checked: boolean) => {
    setOpenRouterEnabled(checked);
    if (!checked && llmDefaultProvider === "openrouter" && minimaxEnabled) {
      setLlmDefaultProvider("minimax");
    }
    if (checked && !minimaxEnabled) {
      setLlmDefaultProvider("openrouter");
    }
  };

  const saveZaloChanges = async () => {
    if (Object.keys(changedPayload).length === 0) return settings;

    const nextZalo = await apiJson<ZaloSettings>(
      "/api/v1/admin/integrations/zalo",
      {
        method: "PUT",
        body: changedPayload,
      },
    );
    setSettings(nextZalo);
    setForm({
      ...emptyForm,
      zalo_oa_app_id: nextZalo.zalo_oa_app_id.value ?? "",
    });
    return nextZalo;
  };

  const saveMinimaxChanges = async () => {
    if (Object.keys(changedMinimaxPayload).length === 0) return minimaxSettings;

    const nextMinimax = await apiJson<MinimaxSettings>(
      "/api/v1/admin/integrations/minimax",
      {
        method: "PUT",
        body: changedMinimaxPayload,
      },
    );
    setMinimaxSettings(nextMinimax);
    setMinimaxForm(emptyMinimaxForm);
    setMinimaxEnabled(nextMinimax.minimax_enable);
    setLlmDefaultProvider(nextMinimax.llm_default_provider);
    return nextMinimax;
  };

  const saveOpenRouterChanges = async () => {
    if (Object.keys(changedOpenRouterPayload).length === 0)
      return openRouterSettings;

    const nextOpenRouter = await apiJson<OpenRouterSettings>(
      "/api/v1/admin/integrations/openrouter",
      {
        method: "PUT",
        body: changedOpenRouterPayload,
      },
    );
    setOpenRouterSettings(nextOpenRouter);
    setOpenRouterForm(emptyOpenRouterForm);
    setOpenRouterEnabled(nextOpenRouter.openrouter_enable);
    setOpenRouterModel(nextOpenRouter.openrouter_agent_model);
    setLlmDefaultProvider(nextOpenRouter.llm_default_provider);
    return nextOpenRouter;
  };

  const saveActiveSection = async () => {
    if (!minimaxEnabled && !openRouterEnabled) {
      notify("Cần bật ít nhất một model cho chatbot.", { type: "warning" });
      return;
    }
    if (
      activeItemId !== "settings-zalo-channel" &&
      activeItemId !== "settings-minimax" &&
      activeItemId !== "settings-openrouter"
    ) return;
    const section = activeItemId;
    setSavingSection(section);
    setSaveResults((current) => ({ ...current, [section]: "idle" }));
    try {
      if (section === "settings-zalo-channel") await saveZaloChanges();
      if (section === "settings-minimax") await saveMinimaxChanges();
      if (section === "settings-openrouter") await saveOpenRouterChanges();
      setSaveResults((current) => ({ ...current, [section]: "success" }));
      notify("Đã lưu cấu hình của mục này", { type: "success" });
    } catch (error) {
      setSaveResults((current) => ({ ...current, [section]: "error" }));
      notify(`Không thể lưu cấu hình: ${(error as Error).message || "Vui lòng thử lại."}`, { type: "error" });
    } finally {
      setSavingSection(null);
    }
  };

  const testChannel = async (
    path: string,
    label: string,
    busySetter: (busy: boolean) => void,
  ) => {
    busySetter(true);
    try {
      await saveZaloChanges();
      const result = await apiJson<ZaloChannelTestResult>(path, {
        method: "POST",
      });
      if (result.connected) {
        notify(`Kết nối ${label} thành công`, { type: "success" });
        return;
      }
      if (result.missing.length > 0) {
        const missing = result.missing
          .map((key) => ZALO_TEST_FIELD_LABELS[key] ?? key)
          .join(", ");
        notify(`Thiếu cấu hình: ${missing}`, { type: "warning" });
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
      "/api/v1/admin/integrations/zalo/bot/test",
      "Zalo Chatbot",
      setTestingBot,
    );

  const testOaConnection = () =>
    testChannel(
      "/api/v1/admin/integrations/zalo/oa/test",
      "Zalo OA",
      setTestingOa,
    );

  const testConfiguredIntegration = async (
    path: string,
    label: string,
    busySetter: (busy: boolean) => void,
    saveChanges: () => Promise<MinimaxSettings | OpenRouterSettings | null>,
  ) => {
    busySetter(true);
    try {
      await saveChanges();
      const result = await apiJson<IntegrationConfigTestResult>(path, {
        method: "POST",
      });
      if (result.configured) {
        notify(`Cấu hình ${label} đã sẵn sàng`, { type: "success" });
        return;
      }
      const missing = result.missing
        .map((key) => INTEGRATION_TEST_FIELD_LABELS[key] ?? key)
        .join(", ");
      notify(`Thiếu cấu hình ${label}: ${missing}`, { type: "warning" });
    } finally {
      busySetter(false);
    }
  };

  const testMinimaxConnection = () =>
    testConfiguredIntegration(
      "/api/v1/admin/integrations/minimax/test",
      "Minimax",
      setTestingMinimax,
      saveMinimaxChanges,
    );

  const testOpenRouterConnection = () =>
    testConfiguredIntegration(
      "/api/v1/admin/integrations/openrouter/test",
      "OpenRouter",
      setTestingOpenRouter,
      saveOpenRouterChanges,
    );

  const changesForActiveSection =
    activeItemId === "settings-zalo-channel"
      ? Object.keys(changedPayload).length > 0
      : activeItemId === "settings-minimax"
        ? Object.keys(changedMinimaxPayload).length > 0
        : activeItemId === "settings-openrouter"
          ? Object.keys(changedOpenRouterPayload).length > 0
          : false;
  const activeSaveResult =
    activeItemId === "settings-zalo-channel" ||
    activeItemId === "settings-minimax" ||
    activeItemId === "settings-openrouter"
      ? saveResults[activeItemId]
      : "idle";

  const activeItem =
    SETTINGS_NAV_ITEMS.find((item) => item.itemId === activeItemId) ??
    SETTINGS_NAV_ITEMS[0];
  const showingIntegrations = activeItem.mode === "integrations";
  const headerCopy = SETTINGS_VIEW_COPY[activeItem.itemId];

  const selectSettingsItem = (itemId: SettingsItemId) => {
    setActiveItemId(itemId);
  };

  useEffect(() => {
    if (!showingIntegrations) return;
    const animationFrame = window.requestAnimationFrame(() => {
      scrollToSettingsSection(activeItem.itemId);
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [activeItem.itemId, showingIntegrations]);

  const renderInWorkspace = (content: ReactNode) => {
    if (isMobile) return content;

    return (
      <div className="inbox-bg-container settings-workspace">
        <InboxIcons />
        <div className="app settings-app" id="app">
          <section className="panel center-panel settings-center-panel">
            {content}
          </section>
        </div>
      </div>
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

    if (activeItemId === "settings-zalo-channel") {
      return (
        <SettingsSectionPanel id="settings-zalo-channel">
          <div className="settings-grid settings-grid-zalo">
            <SettingsCard
              title="Zalo Chatbot"
              icon={<PlugZap className="size-4" />}
            >
              <SecretInput
                id="zalo_bot_token"
                label="Bot Token"
                status={settings?.zalo_bot_token ?? { configured: false }}
                value={form.zalo_bot_token}
                onChange={setValue}
              />
              <SecretInput
                id="zalo_bot_webhook_secret"
                label="Webhook Secret"
                status={
                  settings?.zalo_bot_webhook_secret ?? {
                    configured: false,
                  }
                }
                value={form.zalo_bot_webhook_secret}
                onChange={setValue}
              />
              <div className="settings-oa-actions">
                <Button
                  type="button"
                  variant="outline"
                  className="settings-test-button"
                  onClick={testBotConnection}
                  disabled={savingSection !== null || testingBot || !settings}
                >
                  <Wifi className="size-4" />
                  {testingBot ? "Đang kiểm tra" : "Kiểm tra kết nối"}
                </Button>
              </div>
            </SettingsCard>

            <SettingsCard
              title="Zalo OA"
              icon={<MessageCircle className="size-4" />}
            >
              <div className="settings-oa-fields">
                <div className="settings-field">
                  <div className="flex items-center justify-between gap-3">
                    <Label htmlFor="zalo_oa_app_id">OA App ID</Label>
                  </div>
                  <Input
                    id="zalo_oa_app_id"
                    value={form.zalo_oa_app_id}
                    className="settings-input"
                    onChange={(event) =>
                      setValue("zalo_oa_app_id", event.target.value)
                    }
                  />
                </div>

                <SecretInput
                  id="zalo_oa_secret_key"
                  label="OA Secret"
                  status={settings?.zalo_oa_secret_key ?? { configured: false }}
                  value={form.zalo_oa_secret_key}
                  onChange={setValue}
                />
                <SecretInput
                  id="zalo_oa_access_token"
                  label="OA Access Token"
                  status={
                    settings?.zalo_oa_access_token ?? {
                      configured: false,
                    }
                  }
                  value={form.zalo_oa_access_token}
                  onChange={setValue}
                />
                <SecretInput
                  id="zalo_oa_refresh_token"
                  label="OA Refresh Token"
                  status={
                    settings?.zalo_oa_refresh_token ?? {
                      configured: false,
                    }
                  }
                  value={form.zalo_oa_refresh_token}
                  onChange={setValue}
                />
                <div className="settings-oa-actions">
                  <Button
                    type="button"
                    variant="outline"
                    className="settings-test-button"
                    onClick={testOaConnection}
                    disabled={savingSection !== null || testingOa || !settings}
                  >
                    <Wifi className="size-4" />
                    {testingOa ? "Đang kiểm tra" : "Kiểm tra kết nối"}
                  </Button>
                </div>
                <ZaloOaSignatureHealthBadge
                  health={settings?.zalo_oa_webhook_signature ?? null}
                />
                <ZaloOaSignatureVerifyPanel
                  secretConfigured={
                    (settings?.zalo_oa_secret_key ?? { configured: false })
                      .configured
                  }
                />
              </div>
            </SettingsCard>
          </div>
        </SettingsSectionPanel>
      );
    }

    if (activeItemId === "settings-minimax") {
      return (
        <SettingsSectionPanel id="settings-minimax">
          <div className="settings-grid settings-grid-models">
            <SettingsCard title="Minimax" icon={<Bot className="size-4" />}>
              <ProviderSwitchField
                id="minimax_enable"
                label={minimaxEnabled ? "Bật" : "Tắt"}
                checked={minimaxEnabled}
                onCheckedChange={handleMinimaxEnabledChange}
              />
              <DefaultProviderSwitch
                provider="minimax"
                enabled={minimaxEnabled}
                checked={llmDefaultProvider === "minimax"}
                otherEnabled={openRouterEnabled}
                onCheckedChange={toggleDefaultProvider}
              />
              <div className="settings-readonly-field">
                <span className="settings-readonly-label">Model chat</span>
                <strong>{minimaxSettings?.minimax_agent_model ?? "—"}</strong>
              </div>
              <MinimaxSecretInput
                id="minimax_api_key"
                label="Access Token"
                status={
                  minimaxSettings?.minimax_api_key ?? { configured: false }
                }
                value={minimaxForm.minimax_api_key}
                onChange={setMinimaxValue}
              />
              <div className="settings-oa-actions">
                <Button
                  type="button"
                  variant="outline"
                  className="settings-test-button"
                  onClick={testMinimaxConnection}
                  disabled={savingSection !== null || testingMinimax || !minimaxSettings}
                >
                  <Wifi className="size-4" />
                  {testingMinimax ? "Đang kiểm tra" : "Kiểm tra kết nối"}
                </Button>
              </div>
            </SettingsCard>
          </div>
        </SettingsSectionPanel>
      );
    }

    return (
      <SettingsSectionPanel id="settings-openrouter">
        <div className="settings-grid settings-grid-models">
          <SettingsCard title="OpenRouter" icon={<Cpu className="size-4" />}>
            <ProviderSwitchField
              id="openrouter_enable"
              label={openRouterEnabled ? "Bật" : "Tắt"}
              checked={openRouterEnabled}
              onCheckedChange={handleOpenRouterEnabledChange}
            />
            <DefaultProviderSwitch
              provider="openrouter"
              enabled={openRouterEnabled}
              checked={llmDefaultProvider === "openrouter"}
              otherEnabled={minimaxEnabled}
              onCheckedChange={toggleDefaultProvider}
            />
            <div className="settings-field">
              <Label htmlFor="openrouter_agent_model">Model chatbot</Label>
              <Select
                value={openRouterModel}
                onValueChange={setOpenRouterModel}
              >
                <SelectTrigger
                  id="openrouter_agent_model"
                  className="settings-input"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {OPENROUTER_MODEL_OPTIONS.map((model) => (
                    <SelectItem key={model} value={model}>
                      {model}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <OpenRouterSecretInput
              id="openrouter_api_key"
              label="Access Token"
              status={
                openRouterSettings?.openrouter_api_key ?? {
                  configured: false,
                }
              }
              value={openRouterForm.openrouter_api_key}
              onChange={setOpenRouterValue}
            />
            <div className="settings-oa-actions">
              <Button
                type="button"
                variant="outline"
                className="settings-test-button"
                onClick={testOpenRouterConnection}
                disabled={savingSection !== null || testingOpenRouter || !openRouterSettings}
              >
                <Wifi className="size-4" />
                {testingOpenRouter ? "Đang kiểm tra" : "Kiểm tra kết nối"}
              </Button>
            </div>
          </SettingsCard>
        </div>
      </SettingsSectionPanel>
    );
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
          <SettingsSideNav
            activeItemId={activeItemId}
            onItemSelect={selectSettingsItem}
          />

          <div className="settings-main">
            <header className="ops-command-header settings-command-header">
              <div className="ops-command-title">
                <div className="ops-command-mark">
                  <Settings className="size-5" />
                </div>
                <div className="min-w-0">
                  <p className="ops-kicker">{headerCopy.kicker}</p>
                  <h1>{headerCopy.title}</h1>
                  <p>{headerCopy.description}</p>
                </div>
              </div>
              {showingIntegrations ? (
                <div className="settings-header-actions">
                  <Button
                    className="settings-save-button"
                    onClick={saveActiveSection}
                    disabled={savingSection === activeItemId || !changesForActiveSection}
                  >
                    <Save className="size-4" />
                    {savingSection === activeItemId
                      ? "Đang lưu"
                      : activeSaveResult === "error"
                        ? "Thử lưu lại"
                        : "Lưu cấu hình"}
                  </Button>
                  <p className="settings-save-status" aria-live="polite">
                    {activeSaveResult === "success"
                      ? "Đã lưu mục này. Các mục khác chưa thay đổi."
                      : activeSaveResult === "error"
                        ? "Lưu chưa thành công. Bạn có thể thử lại."
                        : changesForActiveSection
                          ? "Có thay đổi chưa lưu trong mục này."
                          : "Mục này chưa có thay đổi cần lưu."}
                  </p>
                </div>
              ) : null}
            </header>

            {renderSettingsBody()}
          </div>
        </div>
      </div>
    </div>,
  );
};
