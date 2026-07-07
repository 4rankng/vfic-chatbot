import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNotify, usePermissions, useTranslate } from "ra-core";
import {
  Bot,
  Briefcase,
  CheckCircle2,
  Cpu,
  FileText,
  KeyRound,
  MessageCircle,
  PlugZap,
  QrCode,
  Save,
  Settings,
  ShieldCheck,
  Unplug,
  UsersRound,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { vficConfig } from "@/lib/vfic/config";
import { apiJson } from "../providers/rest/api";
import { WorkspaceIconRail } from "../conversations/WorkspaceShell";
import { InboxIcons } from "../conversations/InboxIcons";
import { useIsMobile } from "@/hooks/use-mobile";
import "../conversations/inbox.css";

type SecretStatus = { configured: boolean; preview?: string | null };
type PlainStatus = { configured: boolean; value?: string | null };

type ZaloSettings = {
  zalo_bot_token: SecretStatus;
  zalo_bot_webhook_secret: SecretStatus;
  zalo_oa_app_id: PlainStatus;
  zalo_oa_secret_key: SecretStatus;
  zalo_oa_access_token: SecretStatus;
  zalo_oa_refresh_token: SecretStatus;
  zalo_oa_access_token_expires_at: string | null;
  zalo_oa_connected: boolean;
  zalo_bot_api_base: string;
  zalo_oa_api_base: string;
};

type MinimaxSettings = {
  minimax_api_key: SecretStatus;
  minimax_base_url: string;
  minimax_agent_model: string;
  minimax_safety_model: string;
};

type OpenRouterSettings = {
  openrouter_api_key: SecretStatus;
  openrouter_base_url: string;
  openrouter_agent_model: string;
  openrouter_safety_model: string;
  openrouter_digest_model: string;
  openrouter_embedding_model: string;
  openrouter_embedding_dim: number;
};

type FormState = {
  zalo_bot_token: string;
  zalo_bot_webhook_secret: string;
  zalo_oa_app_id: string;
  zalo_oa_secret_key: string;
  zalo_oa_access_token: string;
};

type MinimaxFormState = {
  minimax_api_key: string;
};

type OpenRouterFormState = {
  openrouter_api_key: string;
};

const emptyForm: FormState = {
  zalo_bot_token: "",
  zalo_bot_webhook_secret: "",
  zalo_oa_app_id: "",
  zalo_oa_secret_key: "",
  zalo_oa_access_token: "",
};

const emptyMinimaxForm: MinimaxFormState = {
  minimax_api_key: "",
};

const emptyOpenRouterForm: OpenRouterFormState = {
  openrouter_api_key: "",
};

type SettingsNavItem =
  | {
      type: "section";
      sectionId: string;
      label: string;
      description: string;
      Icon: LucideIcon;
      active?: boolean;
    }
  | {
      type: "link";
      href: string;
      label: string;
      description: string;
      Icon: LucideIcon;
      active?: boolean;
    };

const SETTINGS_NAV_ITEMS: SettingsNavItem[] = [
  {
    type: "section",
    sectionId: "settings-overview",
    label: "Tổng quan",
    description: "Dự án, agent, mô hình",
    Icon: Settings,
  },
  {
    type: "link",
    href: "/projects",
    label: "Dự án",
    description: "Knowledge base và FAQ",
    Icon: Briefcase,
  },
  {
    type: "link",
    href: "/personas",
    label: "Agent tư vấn",
    description: "Giọng trả lời theo dự án",
    Icon: Workflow,
  },
  {
    type: "section",
    sectionId: "settings-zalo-channel",
    label: "Kênh Zalo",
    description: "Bot Platform và OA",
    Icon: MessageCircle,
  },
  {
    type: "section",
    sectionId: "settings-ai-models",
    label: "Model AI",
    description: "Minimax, OpenRouter",
    Icon: Cpu,
  },
  {
    type: "link",
    href: "/users",
    label: "Người dùng",
    description: "Tài khoản quản trị",
    Icon: UsersRound,
  },
];

const REQUIRED_SETTING_COUNT = 7;

const FieldStatus = ({ status }: { status: SecretStatus | PlainStatus }) => (
  <Badge
    variant="outline"
    className={`settings-status-badge ${status.configured ? "is-ready" : "is-missing"}`}
  >
    {status.configured ? "Đã cấu hình" : "Thiếu"}
  </Badge>
);

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
      <FieldStatus status={status} />
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
      <FieldStatus status={status} />
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
      <FieldStatus status={status} />
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

const ReadOnlySetting = ({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) => (
  <div className="settings-field">
    <Label>{label}</Label>
    <Input readOnly value={value} className="settings-input" />
    {hint ? <p className="settings-field-hint">{hint}</p> : null}
  </div>
);

const SettingsCard = ({
  title,
  description,
  icon,
  children,
  className = "",
}: {
  title: string;
  description?: string;
  icon: ReactNode;
  children: ReactNode;
  className?: string;
}) => (
  <section className={`settings-card ${className}`}>
    <div className="settings-card-header">
      <div className="settings-card-icon">{icon}</div>
      <div className="min-w-0">
        <div data-slot="card-title">{title}</div>
        {description ? (
          <p className="settings-card-description">{description}</p>
        ) : null}
      </div>
    </div>
    <div className="settings-card-content">{children}</div>
  </section>
);

const SettingsSectionPanel = ({
  id,
  title,
  description,
  icon,
  children,
}: {
  id: string;
  title: string;
  description: string;
  icon: ReactNode;
  children: ReactNode;
}) => (
  <section className="settings-section-panel" id={id}>
    <div className="settings-section-heading">
      <div className="settings-section-icon">{icon}</div>
      <div className="min-w-0">
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
    </div>
    {children}
  </section>
);

const CORE_SETTINGS_LINKS: Array<{
  href: string;
  title: string;
  description: string;
  Icon: LucideIcon;
  primary?: boolean;
}> = [
  {
    href: "/projects",
    title: "Thiết lập dự án",
    description:
      "Mỗi dự án gồm knowledge base, FAQ và dữ liệu tư vấn trong cùng một workspace.",
    Icon: Briefcase,
    primary: true,
  },
  {
    href: "/personas",
    title: "Agent tư vấn",
    description:
      "Chọn giọng tư vấn và phân công agent sau khi dữ liệu dự án sẵn sàng.",
    Icon: FileText,
  },
];

const SettingsShortcutGrid = () => (
  <section className="settings-shortcut-grid" aria-label="Thiết lập chính">
    {CORE_SETTINGS_LINKS.map(({ href, title, description, Icon, primary }) => (
      <Link
        key={title}
        to={href}
        className={`settings-shortcut-card${primary ? " is-primary" : ""}`}
      >
        <span className="settings-card-icon">
          <Icon className="size-4" />
        </span>
        <span>
          <strong>{title}</strong>
          <p>{description}</p>
        </span>
      </Link>
    ))}
  </section>
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
  activeSectionId,
  configuredCount,
  isLoading,
  onSectionSelect,
}: {
  activeSectionId: string;
  configuredCount: number;
  isLoading: boolean;
  onSectionSelect: (sectionId: string) => void;
}) => (
  <aside className="settings-side-nav" aria-label="Nhóm cài đặt">
    <div className="settings-side-nav-header">
      <span>Cài đặt</span>
      <strong>
        {isLoading
          ? "Đang tải"
          : `${configuredCount}/${REQUIRED_SETTING_COUNT}`}
      </strong>
    </div>
    <nav className="settings-side-nav-list">
      {SETTINGS_NAV_ITEMS.map((item) => {
        const Icon = item.Icon;
        const content = (
          <>
            <span className="settings-side-nav-icon">
              <Icon className="size-4" />
            </span>
            <span className="settings-side-nav-copy">
              <strong>{item.label}</strong>
              <span>{item.description}</span>
            </span>
          </>
        );

        if (item.type === "link") {
          return (
            <Link
              key={item.label}
              to={item.href}
              className={`settings-side-nav-link${
                item.active ? " is-active" : ""
              }`}
            >
              {content}
            </Link>
          );
        }

        const active = item.sectionId === activeSectionId;

        return (
          <button
            key={item.label}
            type="button"
            className={`settings-side-nav-link${active ? " is-active" : ""}`}
            onClick={() => onSectionSelect(item.sectionId)}
          >
            {content}
          </button>
        );
      })}
    </nav>
    <div className="settings-side-nav-footer">
      <CheckCircle2 className="size-4" />
      <span>Khóa bí mật được lưu mã hóa ở backend.</span>
    </div>
  </aside>
);

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
  const [activeSectionId, setActiveSectionId] = useState("settings-overview");
  const [saving, setSaving] = useState(false);
  const [oaConnecting, setOaConnecting] = useState(false);
  const [oaDisconnecting, setOaDisconnecting] = useState(false);
  const oauthPopupRef = useRef<Window | null>(null);

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
    const value = minimaxForm.minimax_api_key.trim();
    return value ? { minimax_api_key: value } : {};
  }, [minimaxForm]);

  const changedOpenRouterPayload = useMemo(() => {
    const value = openRouterForm.openrouter_api_key.trim();
    return value ? { openrouter_api_key: value } : {};
  }, [openRouterForm]);

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

  const save = async () => {
    setSaving(true);
    try {
      const [nextZalo, nextMinimax, nextOpenRouter] = await Promise.all([
        Object.keys(changedPayload).length > 0
          ? apiJson<ZaloSettings>("/api/v1/admin/integrations/zalo", {
              method: "PUT",
              body: changedPayload,
            })
          : Promise.resolve(settings),
        Object.keys(changedMinimaxPayload).length > 0
          ? apiJson<MinimaxSettings>("/api/v1/admin/integrations/minimax", {
              method: "PUT",
              body: changedMinimaxPayload,
            })
          : Promise.resolve(minimaxSettings),
        Object.keys(changedOpenRouterPayload).length > 0
          ? apiJson<OpenRouterSettings>(
              "/api/v1/admin/integrations/openrouter",
              {
                method: "PUT",
                body: changedOpenRouterPayload,
              },
            )
          : Promise.resolve(openRouterSettings),
      ]);
      if (nextZalo) setSettings(nextZalo);
      if (nextMinimax) setMinimaxSettings(nextMinimax);
      if (nextOpenRouter) setOpenRouterSettings(nextOpenRouter);
      setForm({
        ...emptyForm,
        zalo_oa_app_id: nextZalo?.zalo_oa_app_id.value ?? "",
      });
      setMinimaxForm(emptyMinimaxForm);
      setOpenRouterForm(emptyOpenRouterForm);
      notify("Đã lưu cấu hình", { type: "success" });
    } finally {
      setSaving(false);
    }
  };

  const hasChanges =
    Object.keys(changedPayload).length > 0 ||
    Object.keys(changedMinimaxPayload).length > 0 ||
    Object.keys(changedOpenRouterPayload).length > 0;

  const selectSettingsSection = (sectionId: string) => {
    setActiveSectionId(sectionId);
    scrollToSettingsSection(sectionId);
  };

  // Origin that serves the OAuth callback page (the backend). In prod the CRM and
  // backend share an origin; in dev apiBaseUrl points at the tunneled backend.
  const oauthExpectedOrigin = vficConfig.apiBaseUrl
    ? new URL(vficConfig.apiBaseUrl).origin
    : window.location.origin;

  const connectOa = async () => {
    if (oaConnecting) return;
    setOaConnecting(true);
    try {
      const { authorize_url } = await apiJson<{ authorize_url: string }>(
        "/api/v1/admin/integrations/zalo/oauth/start",
        { method: "POST" },
      );
      const popup = window.open(authorize_url, "zalo_oauth", "width=560,height=720");
      if (!popup) {
        notify(
          "Vui lòng cho phép cửa sổ popup để quét mã QR kết nối OA.",
          { type: "warning" },
        );
        return;
      }
      oauthPopupRef.current = popup;
      let settled = false;
      const cleanup = () => {
        settled = true;
        window.removeEventListener("message", onMessage);
        if (pollHandle !== undefined) window.clearInterval(pollHandle);
      };
      const onMessage = (event: MessageEvent) => {
        if (event.origin !== oauthExpectedOrigin) return;
        const data = event.data as
          | { type?: string; oa_name?: string; message?: string }
          | null;
        if (
          !data ||
          (data.type !== "zalo_oauth_success" && data.type !== "zalo_oauth_error")
        ) {
          return;
        }
        cleanup();
        if (data.type === "zalo_oauth_success") {
          notify(
            data.oa_name ? `Đã kết nối OA: ${data.oa_name}` : "Đã kết nối OA",
            { type: "success" },
          );
          void load();
        } else {
          notify(`Kết nối OA thất bại: ${data.message ?? ""}`, { type: "error" });
        }
      };
      // If the admin closes the popup without finishing, drop the listener so it
      // can't fire on a later, unrelated message.
      let pollHandle: number | undefined = window.setInterval(() => {
        if (popup.closed) {
          if (!settled) {
            window.removeEventListener("message", onMessage);
            settled = true;
          }
          if (pollHandle !== undefined) window.clearInterval(pollHandle);
        }
      }, 800);
      window.addEventListener("message", onMessage);
    } catch {
      notify("Không bắt đầu được kết nối OA.", { type: "error" });
    } finally {
      setOaConnecting(false);
    }
  };

  const disconnectOa = async () => {
    if (oaDisconnecting) return;
    setOaDisconnecting(true);
    try {
      await apiJson<{ disconnected: boolean }>(
        "/api/v1/admin/integrations/zalo/oauth",
        { method: "DELETE" },
      );
      notify("Đã ngắt kết nối OA.", { type: "success" });
      void load();
    } catch {
      notify("Ngắt kết nối OA thất bại.", { type: "error" });
    } finally {
      setOaDisconnecting(false);
    }
  };

  const configuredCount = useMemo(() => {
    const statuses: Array<SecretStatus | PlainStatus | undefined> = [
      settings?.zalo_bot_token,
      settings?.zalo_bot_webhook_secret,
      settings?.zalo_oa_app_id,
      settings?.zalo_oa_secret_key,
      settings?.zalo_oa_access_token,
      minimaxSettings?.minimax_api_key,
      openRouterSettings?.openrouter_api_key,
    ];

    return statuses.filter((status) => status?.configured).length;
  }, [minimaxSettings, openRouterSettings, settings]);

  const renderInWorkspace = (content: ReactNode) => {
    if (isMobile) return content;

    return (
      <div className="inbox-bg-container settings-workspace">
        <InboxIcons />
        <main className="app settings-app" id="app">
          <WorkspaceIconRail />
          <section className="panel center-panel settings-center-panel">
            {content}
          </section>
        </main>
      </div>
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
            activeSectionId={activeSectionId}
            configuredCount={configuredCount}
            isLoading={permissionsPending || !settings}
            onSectionSelect={selectSettingsSection}
          />

          <div className="settings-main" id="settings-overview">
            <header className="ops-command-header settings-command-header">
              <div className="ops-command-title">
                <div className="ops-command-mark">
                  <Settings className="size-5" />
                </div>
                <div className="min-w-0">
                  <p className="ops-kicker">Thiết lập dự án</p>
                  <h1>Cấu hình hệ thống</h1>
                  <p>
                    Quản lý dự án, agent tư vấn, kênh Zalo và model AI trong
                    cùng một bảng cài đặt.
                  </p>
                </div>
              </div>
              <div className="settings-header-actions">
                <Button
                  className="settings-save-button"
                  onClick={save}
                  disabled={saving || !hasChanges}
                >
                  <Save className="size-4" />
                  Lưu
                </Button>
              </div>
            </header>

            <SettingsShortcutGrid />

            <SettingsSectionPanel
              id="settings-zalo-channel"
              title="Kênh Zalo"
              description="Kết nối Bot Platform và Official Account để nhận, gửi và đồng bộ hội thoại."
              icon={<MessageCircle className="size-4" />}
            >
              <div className="settings-grid">
                <SettingsCard
                  title="ChatBot"
                  description="Token Bot Platform và khóa xác minh webhook."
                  icon={<PlugZap className="size-4" />}
                >
                  <SecretInput
                    id="zalo_bot_token"
                    label="Token bot"
                    status={settings?.zalo_bot_token ?? { configured: false }}
                    value={form.zalo_bot_token}
                    onChange={setValue}
                  />
                  <SecretInput
                    id="zalo_bot_webhook_secret"
                    label="Khóa bí mật webhook"
                    status={
                      settings?.zalo_bot_webhook_secret ?? {
                        configured: false,
                      }
                    }
                    value={form.zalo_bot_webhook_secret}
                    onChange={setValue}
                  />
                </SettingsCard>

                <SettingsCard
                  title="Tài khoản OA"
                  description="Thông tin Official Account dùng cho kênh OA."
                  icon={<KeyRound className="size-4" />}
                >
                  <div className="settings-field">
                    <div className="flex items-center justify-between gap-3">
                      <Label htmlFor="zalo_oa_app_id">OA App ID</Label>
                      <FieldStatus
                        status={
                          settings?.zalo_oa_app_id ?? { configured: false }
                        }
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
                  </div>
                  <SecretInput
                    id="zalo_oa_secret_key"
                    label="Khóa bí mật OA"
                    status={
                      settings?.zalo_oa_secret_key ?? { configured: false }
                    }
                    value={form.zalo_oa_secret_key}
                    onChange={setValue}
                  />
                  <SecretInput
                    id="zalo_oa_access_token"
                    label="Token truy cập OA"
                    status={
                      settings?.zalo_oa_access_token ?? { configured: false }
                    }
                    value={form.zalo_oa_access_token}
                    onChange={setValue}
                  />
                </SettingsCard>
              </div>
            </SettingsSectionPanel>

            <SettingsSectionPanel
              id="settings-ai-models"
              title="Model AI"
              description="Quản lý khóa model chính, model safety và embedding phục vụ trả lời có căn cứ."
              icon={<ShieldCheck className="size-4" />}
            >
              <div className="settings-grid">
                <SettingsCard
                  title="Minimax"
                  description="Model chính cho agent và kiểm tra safety."
                  icon={<Bot className="size-4" />}
                >
                  <MinimaxSecretInput
                    id="minimax_api_key"
                    label="Token Minimax"
                    status={
                      minimaxSettings?.minimax_api_key ?? { configured: false }
                    }
                    value={minimaxForm.minimax_api_key}
                    onChange={setMinimaxValue}
                  />
                  <ReadOnlySetting
                    label="Model ChatBot"
                    value={minimaxSettings?.minimax_agent_model ?? ""}
                  />
                  <ReadOnlySetting
                    label="Model Safety"
                    value={minimaxSettings?.minimax_safety_model ?? ""}
                  />
                </SettingsCard>

                <SettingsCard
                  title="OpenRouter"
                  description="Fallback, digest và embedding cho knowledge base."
                  icon={<Cpu className="size-4" />}
                  className="settings-card-wide"
                >
                  <OpenRouterSecretInput
                    id="openrouter_api_key"
                    label="Token OpenRouter"
                    status={
                      openRouterSettings?.openrouter_api_key ?? {
                        configured: false,
                      }
                    }
                    value={openRouterForm.openrouter_api_key}
                    onChange={setOpenRouterValue}
                  />
                  <ReadOnlySetting
                    label="Model tóm tắt huấn luyện"
                    value={openRouterSettings?.openrouter_digest_model ?? ""}
                    hint="Tạo digest JSON và catalog card từ tài liệu thô."
                  />
                  <ReadOnlySetting
                    label="Model embedding"
                    value={
                      openRouterSettings
                        ? `${openRouterSettings.openrouter_embedding_model} · ${openRouterSettings.openrouter_embedding_dim}d`
                        : "openai/text-embedding-3-large · 3072d"
                    }
                    hint="Dùng cho indexing và retrieval; giữ 3072 chiều để tương thích pgvector hiện tại."
                  />
                  <ReadOnlySetting
                    label="Model ChatBot"
                    value={openRouterSettings?.openrouter_agent_model ?? ""}
                  />
                  <ReadOnlySetting
                    label="Model Safety"
                    value={openRouterSettings?.openrouter_safety_model ?? ""}
                  />
                </SettingsCard>
              </div>
            </SettingsSectionPanel>
          </div>
        </div>
      </div>
    </div>,
  );
};
