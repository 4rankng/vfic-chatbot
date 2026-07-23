import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useNotify, usePermissions, useTranslate } from "ra-core";
import {
  Bot,
  ChevronDown,
  Copy,
  Cpu,
  Eye,
  EyeOff,
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
  type IntegrationConfigTestResult,
  type LlmProvider,
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
  SettingsFieldStatus,
  SettingsGroupStatus,
  type SettingsStatusState,
} from "./SettingsFieldStatus";
import "../conversations/inbox.css";
import "./settings.css";

type FormState = ZaloFormState;

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

const ZALO_TEST_FIELD_LABELS: Record<string, string> = {
  zalo_bot_token: "Bot Token",
  zalo_oa_app_id: "Zalo App ID",
  zalo_oa_secret_key: "Bot Secret",
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
  | "settings-facebook-messenger"
  | "settings-minimax"
  | "settings-openrouter"
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
  "settings-minimax": {
    kicker: "Model chính",
    title: "Minimax",
    description: "Khóa API cho model Agent chính.",
  },
  "settings-openrouter": {
    kicker: "Model dự phòng",
    title: "OpenRouter",
    description: "Fallback và embeddings khi model chính gián đoạn.",
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

const SecretField = ({
  id,
  label,
  status,
  statusState = "ready",
  value,
  placeholder,
  onValueChange,
}: {
  id: string;
  label: string;
  status: SecretStatus;
  statusState?: SettingsStatusState;
  value: string;
  placeholder: string;
  onValueChange: (value: string) => void;
}) => {
  const [isVisible, setIsVisible] = useState(false);

  return (
    <div className="settings-field">
      <div className="settings-field-label-row">
        <Label htmlFor={id}>{label}</Label>
        <SettingsFieldStatus
          configured={status.configured}
          state={statusState}
        />
      </div>
      <div className="settings-sensitive-input">
        <Input
          id={id}
          type={isVisible ? "text" : "password"}
          autoComplete="off"
          value={value}
          placeholder={
            status.preview ? `Hiện tại: ${status.preview}` : placeholder
          }
          className="settings-input"
          onChange={(event) => onValueChange(event.target.value)}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="settings-input-action md:hidden"
          aria-label={isVisible ? `Ẩn ${label}` : `Hiện ${label}`}
          onClick={() => setIsVisible((visible) => !visible)}
        >
          {isVisible ? <EyeOff /> : <Eye />}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="settings-input-action md:hidden"
          aria-label={`Sao chép ${label}`}
          disabled={!value}
          onClick={() => void navigator.clipboard.writeText(value)}
        >
          <Copy />
        </Button>
      </div>
    </div>
  );
};

const SecretInput = ({
  id,
  label,
  status,
  statusState,
  value,
  onChange,
}: {
  id: keyof FormState;
  label: string;
  status: SecretStatus;
  statusState?: SettingsStatusState;
  value: string;
  onChange: (key: keyof FormState, value: string) => void;
}) => (
  <SecretField
    id={id}
    label={label}
    status={status}
    statusState={statusState}
    value={value}
    placeholder="Nhập giá trị"
    onValueChange={(nextValue) => onChange(id, nextValue)}
  />
);

const MinimaxSecretInput = ({
  id,
  label,
  status,
  statusState,
  value,
  onChange,
}: {
  id: keyof MinimaxFormState;
  label: string;
  status: SecretStatus;
  statusState?: SettingsStatusState;
  value: string;
  onChange: (key: keyof MinimaxFormState, value: string) => void;
}) => (
  <SecretField
    id={id}
    label={label}
    status={status}
    statusState={statusState}
    value={value}
    placeholder="Dán token Minimax"
    onValueChange={(nextValue) => onChange(id, nextValue)}
  />
);

const OpenRouterSecretInput = ({
  id,
  label,
  status,
  statusState,
  value,
  onChange,
}: {
  id: keyof OpenRouterFormState;
  label: string;
  status: SecretStatus;
  statusState?: SettingsStatusState;
  value: string;
  onChange: (key: keyof OpenRouterFormState, value: string) => void;
}) => (
  <SecretField
    id={id}
    label={label}
    status={status}
    statusState={statusState}
    value={value}
    placeholder="Dán token OpenRouter"
    onValueChange={(nextValue) => onChange(id, nextValue)}
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
  const [minimaxSettings, setMinimaxSettings] =
    useState<MinimaxSettings | null>(null);
  const [openRouterSettings, setOpenRouterSettings] =
    useState<OpenRouterSettings | null>(null);
  const [settingsStatusState, setSettingsStatusState] =
    useState<SettingsStatusState>("loading");
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
    resolveInitialSettingsItemId,
  );
  const [testingBot, setTestingBot] = useState(false);
  const [testingOa, setTestingOa] = useState(false);
  const [testingMinimax, setTestingMinimax] = useState(false);
  const [testingOpenRouter, setTestingOpenRouter] = useState(false);

  const load = useCallback(async () => {
    setSettingsStatusState("loading");
    try {
      const {
        zalo: data,
        minimax: minimaxData,
        openRouter: openRouterData,
      } = await zaloIntegrationGateway.loadSettingsBundle();
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

  const saveMinimaxChanges = async () => {
    if (Object.keys(changedMinimaxPayload).length === 0) return minimaxSettings;

    const nextMinimax = await zaloIntegrationGateway.saveMinimaxSettings(
      changedMinimaxPayload,
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

    const nextOpenRouter = await zaloIntegrationGateway.saveOpenRouterSettings(
      changedOpenRouterPayload,
    );
    setOpenRouterSettings(nextOpenRouter);
    setOpenRouterForm(emptyOpenRouterForm);
    setOpenRouterEnabled(nextOpenRouter.openrouter_enable);
    setOpenRouterModel(nextOpenRouter.openrouter_agent_model);
    setLlmDefaultProvider(nextOpenRouter.llm_default_provider);
    return nextOpenRouter;
  };

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

  const testConfiguredIntegration = async (
    request: () => Promise<IntegrationConfigTestResult>,
    label: string,
    busySetter: (busy: boolean) => void,
    saveChanges: () => Promise<MinimaxSettings | OpenRouterSettings | null>,
  ) => {
    busySetter(true);
    try {
      await saveChanges();
      const result = await request();
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
      zaloIntegrationGateway.testMinimaxConnection,
      "Minimax",
      setTestingMinimax,
      saveMinimaxChanges,
    );

  const testOpenRouterConnection = () =>
    testConfiguredIntegration(
      zaloIntegrationGateway.testOpenRouterConnection,
      "OpenRouter",
      setTestingOpenRouter,
      saveOpenRouterChanges,
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
  const minimaxConfigured = minimaxSettings?.minimax_api_key.configured ? 1 : 0;
  const openRouterConfigured = openRouterSettings?.openrouter_api_key.configured
    ? 1
    : 0;

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
                status={settings?.zalo_bot_token ?? { configured: false }}
                statusState={settingsStatusState}
                value={form.zalo_bot_token}
                onChange={setValue}
              />
              <SecretInput
                id="zalo_bot_webhook_secret"
                label="Bot Secret"
                status={
                  settings?.zalo_bot_webhook_secret ?? {
                    configured: false,
                  }
                }
                statusState={settingsStatusState}
                value={form.zalo_bot_webhook_secret}
                onChange={setValue}
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
                <div className="settings-field">
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
                    className="settings-copy-app-id md:hidden"
                    aria-label="Sao chép Zalo App ID"
                    disabled={!form.zalo_oa_app_id}
                    onClick={() =>
                      void navigator.clipboard.writeText(form.zalo_oa_app_id)
                    }
                  >
                    <Copy />
                  </Button>
                </div>

                <SecretInput
                  id="zalo_oa_secret_key"
                  label="Bot Secret"
                  status={settings?.zalo_oa_secret_key ?? { configured: false }}
                  statusState={settingsStatusState}
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
                  statusState={settingsStatusState}
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
                  statusState={settingsStatusState}
                  value={form.zalo_oa_refresh_token}
                  onChange={setValue}
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

    if (activeItemId === "settings-minimax") {
      return (
        <SettingsSectionPanel id="settings-minimax">
          <div className="settings-grid settings-grid-models">
            <SettingsGroup
              title="Minimax"
              icon={<Bot className="size-4" />}
              meta={
                <SettingsGroupStatus
                  configured={minimaxConfigured}
                  total={1}
                  disabled={!minimaxEnabled}
                  state={settingsStatusState}
                />
              }
            >
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
                statusState={settingsStatusState}
                value={minimaxForm.minimax_api_key}
                onChange={setMinimaxValue}
              />
              <div className="settings-oa-actions">
                <Button
                  type="button"
                  className="settings-test-button settings-primary-action tt-btn-touch"
                  onClick={testMinimaxConnection}
                  disabled={testingMinimax || !minimaxSettings}
                  aria-busy={testingMinimax}
                >
                  <Wifi className="size-4" />
                  {testingMinimax ? "Đang kiểm tra" : "Lưu & kiểm tra"}
                </Button>
              </div>
            </SettingsGroup>
          </div>
        </SettingsSectionPanel>
      );
    }

    return (
      <SettingsSectionPanel id="settings-openrouter">
        <div className="settings-grid settings-grid-models">
          <SettingsGroup
            title="OpenRouter"
            icon={<Cpu className="size-4" />}
            meta={
              <SettingsGroupStatus
                configured={openRouterConfigured}
                total={1}
                disabled={!openRouterEnabled}
                state={settingsStatusState}
              />
            }
          >
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
              statusState={settingsStatusState}
              value={openRouterForm.openrouter_api_key}
              onChange={setOpenRouterValue}
            />
            <div className="settings-oa-actions">
              <Button
                type="button"
                className="settings-test-button settings-primary-action tt-btn-touch"
                onClick={testOpenRouterConnection}
                disabled={testingOpenRouter || !openRouterSettings}
                aria-busy={testingOpenRouter}
              >
                <Wifi className="size-4" />
                {testingOpenRouter ? "Đang kiểm tra" : "Lưu & kiểm tra"}
              </Button>
            </div>
          </SettingsGroup>
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
