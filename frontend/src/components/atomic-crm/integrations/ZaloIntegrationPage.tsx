import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNotify, usePermissions, useTranslate } from "ra-core";
import {
  Bot,
  Briefcase,
  Cpu,
  FileText,
  KeyRound,
  PlugZap,
  Save,
  Settings,
  type LucideIcon,
} from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
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
  icon,
  children,
  className = "",
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
  className?: string;
}) => (
  <section className={`settings-card ${className}`}>
    <div className="settings-card-header">
      <div className="settings-card-icon">{icon}</div>
      <div className="min-w-0">
        <div data-slot="card-title">{title}</div>
      </div>
    </div>
    <div className="settings-card-content">{children}</div>
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
        <header className="ops-command-header settings-command-header">
          <div className="ops-command-title">
            <div className="ops-command-mark">
              <Settings className="size-5" />
            </div>
            <div className="min-w-0">
              <p className="ops-kicker">Thiết lập dự án</p>
              <h1>Cấu hình hệ thống</h1>
              <p>
                Dự án là trung tâm: tạo dự án, nạp knowledge base, kiểm tra
                dữ liệu rồi mới bật agent và model AI.
              </p>
            </div>
          </div>
          <div className="settings-header-actions">
            <Button onClick={save} disabled={saving || !hasChanges}>
              <Save className="size-4" />
              Lưu
            </Button>
          </div>
        </header>

        <SettingsShortcutGrid />

        <div className="settings-grid">
          <SettingsCard
            title="ChatBot"
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
                settings?.zalo_bot_webhook_secret ?? { configured: false }
              }
              value={form.zalo_bot_webhook_secret}
              onChange={setValue}
            />
          </SettingsCard>

          <SettingsCard
            title="Tài khoản OA"
            icon={<KeyRound className="size-4" />}
          >
            <div className="settings-field">
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="zalo_oa_app_id">OA App ID</Label>
                <FieldStatus
                  status={settings?.zalo_oa_app_id ?? { configured: false }}
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
              status={settings?.zalo_oa_secret_key ?? { configured: false }}
              value={form.zalo_oa_secret_key}
              onChange={setValue}
            />
            <SecretInput
              id="zalo_oa_access_token"
              label="Token truy cập OA"
              status={settings?.zalo_oa_access_token ?? { configured: false }}
              value={form.zalo_oa_access_token}
              onChange={setValue}
            />
          </SettingsCard>

          <SettingsCard title="Minimax" icon={<Bot className="size-4" />}>
            <MinimaxSecretInput
              id="minimax_api_key"
              label="Token Minimax"
              status={minimaxSettings?.minimax_api_key ?? { configured: false }}
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
            icon={<Cpu className="size-4" />}
            className="settings-card-wide"
          >
            <OpenRouterSecretInput
              id="openrouter_api_key"
              label="Token OpenRouter"
              status={
                openRouterSettings?.openrouter_api_key ?? { configured: false }
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
      </div>
    </div>,
  );
};
