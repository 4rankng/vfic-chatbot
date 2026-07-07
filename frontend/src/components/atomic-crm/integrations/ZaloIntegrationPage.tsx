import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNotify, usePermissions, useTranslate } from "ra-core";
import {
  Bot,
  Briefcase,
  CheckCircle2,
  Cpu,
  MessageCircle,
  PlugZap,
  Save,
  Settings,
  UsersRound,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
};

type OpenRouterSettings = {
  openrouter_api_key: SecretStatus;
  openrouter_base_url: string;
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

type SettingsSectionNavItem = {
  sectionId: string;
  label: string;
  description: string;
  Icon: LucideIcon;
};

type SettingsWorkspaceLink = {
  href: string;
  label: string;
  description: string;
  Icon: LucideIcon;
};

const SETTINGS_SECTION_ITEMS: SettingsSectionNavItem[] = [
  {
    sectionId: "settings-zalo-channel",
    label: "Kênh Zalo",
    description: "Bot Platform và OA",
    Icon: MessageCircle,
  },
  {
    sectionId: "settings-ai-models",
    label: "Model AI",
    description: "Minimax, OpenRouter",
    Icon: Cpu,
  },
];

const SETTINGS_WORKSPACE_LINKS: SettingsWorkspaceLink[] = [
  {
    href: "/projects",
    label: "Dự án",
    description: "Knowledge base và FAQ",
    Icon: Briefcase,
  },
  {
    href: "/personas",
    label: "Agent tư vấn",
    description: "Giọng trả lời theo dự án",
    Icon: Workflow,
  },
  {
    href: "/users",
    label: "Người dùng",
    description: "Tài khoản quản trị",
    Icon: UsersRound,
  },
];

const REQUIRED_SETTING_COUNT = 7;

const countConfigured = (
  statuses: Array<SecretStatus | PlainStatus | undefined>,
) => statuses.filter((status) => status?.configured).length;

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

const SettingsCard = ({
  title,
  description,
  icon,
  meta,
  children,
  className = "",
}: {
  title: string;
  description?: string;
  icon: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
}) => (
  <section className={`settings-card ${className}`}>
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
    <div className="settings-side-nav-group">
      <span className="settings-side-nav-group-label">Trong trang</span>
      <nav className="settings-side-nav-list">
        {SETTINGS_SECTION_ITEMS.map((item) => {
          const active = item.sectionId === activeSectionId;

          return (
            <button
              key={item.label}
              type="button"
              className={`settings-side-nav-link${active ? " is-active" : ""}`}
              onClick={() => onSectionSelect(item.sectionId)}
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
    <div className="settings-side-nav-group">
      <span className="settings-side-nav-group-label">Liên kết</span>
      <nav className="settings-side-nav-list">
        {SETTINGS_WORKSPACE_LINKS.map((item) => (
          <Link
            key={item.label}
            to={item.href}
            className="settings-side-nav-link"
          >
            <SettingsNavLinkContent
              label={item.label}
              description={item.description}
              Icon={item.Icon}
            />
          </Link>
        ))}
      </nav>
    </div>
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
  const [activeSectionId, setActiveSectionId] = useState(
    "settings-zalo-channel",
  );
  const [saving, setSaving] = useState(false);

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

  const configuredCount = useMemo(() => {
    return countConfigured([
      settings?.zalo_bot_token,
      settings?.zalo_bot_webhook_secret,
      settings?.zalo_oa_app_id,
      settings?.zalo_oa_secret_key,
      settings?.zalo_oa_access_token,
      minimaxSettings?.minimax_api_key,
      openRouterSettings?.openrouter_api_key,
    ]);
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

          <div className="settings-main">
            <header className="ops-command-header settings-command-header">
              <div className="ops-command-title">
                <div className="ops-command-mark">
                  <Settings className="size-5" />
                </div>
                <div className="min-w-0">
                  <p className="ops-kicker">Trung tâm cấu hình</p>
                  <h1>Cài đặt hệ thống</h1>
                  <p>
                    Gom các khóa tích hợp, kết nối Zalo và model AI theo đúng
                    thứ tự vận hành.
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
                  Lưu cấu hình
                </Button>
              </div>
            </header>

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
                      status={
                        settings?.zalo_oa_secret_key ?? { configured: false }
                      }
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
                  </div>

                </SettingsCard>
              </div>
            </SettingsSectionPanel>

            <SettingsSectionPanel id="settings-ai-models">
              <div className="settings-grid settings-grid-models">
                <SettingsCard
                  title="Minimax"
                  icon={<Bot className="size-4" />}
                >
                  <MinimaxSecretInput
                    id="minimax_api_key"
                    label="Access Token"
                    status={
                      minimaxSettings?.minimax_api_key ?? { configured: false }
                    }
                    value={minimaxForm.minimax_api_key}
                    onChange={setMinimaxValue}
                  />
                </SettingsCard>

                <SettingsCard
                  title="OpenRouter"
                  icon={<Cpu className="size-4" />}
                >
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
                </SettingsCard>
              </div>
            </SettingsSectionPanel>
          </div>
        </div>
      </div>
    </div>,
  );
};
