import { useEffect, useMemo, useState } from "react";
import { useNotify, usePermissions, useTranslate } from "ra-core";
import { KeyRound, RefreshCw, Save } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { apiJson } from "../providers/rest/api";

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

type FormState = {
  zalo_bot_token: string;
  zalo_bot_webhook_secret: string;
  zalo_oa_app_id: string;
  zalo_oa_secret_key: string;
  zalo_oa_access_token: string;
};

const emptyForm: FormState = {
  zalo_bot_token: "",
  zalo_bot_webhook_secret: "",
  zalo_oa_app_id: "",
  zalo_oa_secret_key: "",
  zalo_oa_access_token: "",
};

const FieldStatus = ({ status }: { status: SecretStatus | PlainStatus }) => (
  <Badge variant={status.configured ? "default" : "secondary"}>
    {status.configured ? "Configured" : "Missing"}
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
  <div className="space-y-2">
    <div className="flex items-center justify-between gap-3">
      <Label htmlFor={id}>{label}</Label>
      <FieldStatus status={status} />
    </div>
    <Input
      id={id}
      type="password"
      autoComplete="off"
      value={value}
      placeholder={status.preview ? `Current: ${status.preview}` : "Enter value"}
      onChange={(event) => onChange(id, event.target.value)}
    />
  </div>
);

export const ZaloIntegrationPage = () => {
  const translate = useTranslate();
  const notify = useNotify();
  const { permissions, isPending: permissionsPending } = usePermissions();
  const [settings, setSettings] = useState<ZaloSettings | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const data = await apiJson<ZaloSettings>(
        "/api/v1/admin/integrations/zalo",
      );
      setSettings(data);
      setForm((current) => ({
        ...current,
        zalo_oa_app_id: data.zalo_oa_app_id.value ?? "",
      }));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!permissionsPending && permissions === "admin") {
      void load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [permissions, permissionsPending]);

  const changedPayload = useMemo(() => {
    const payload: Partial<FormState> = {};
    for (const key of Object.keys(form) as (keyof FormState)[]) {
      const value = form[key].trim();
      if (!value) continue;
      if (key === "zalo_oa_app_id" && value === settings?.zalo_oa_app_id.value) {
        continue;
      }
      payload[key] = value;
    }
    return payload;
  }, [form, settings]);

  const setValue = (key: keyof FormState, value: string) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const save = async () => {
    setSaving(true);
    try {
      const next = await apiJson<ZaloSettings>("/api/v1/admin/integrations/zalo", {
        method: "PUT",
        body: changedPayload,
      });
      setSettings(next);
      setForm({
        ...emptyForm,
        zalo_oa_app_id: next.zalo_oa_app_id.value ?? "",
      });
      notify("Zalo settings saved", { type: "success" });
    } finally {
      setSaving(false);
    }
  };

  if (!permissionsPending && permissions !== "admin") {
    return (
      <div className="py-10 text-center text-sm text-muted-foreground">
        {translate("ra.auth.access_denied", { _: "Access denied" })}
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pb-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-normal">
            Zalo Integration
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage Bot Platform and Official Account credentials.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={load} disabled={loading || saving}>
            <RefreshCw className="size-4" />
            Refresh
          </Button>
          <Button
            onClick={save}
            disabled={saving || Object.keys(changedPayload).length === 0}
          >
            <Save className="size-4" />
            Save
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <KeyRound className="size-4" />
            Bot Platform
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <SecretInput
            id="zalo_bot_token"
            label="Bot token"
            status={settings?.zalo_bot_token ?? { configured: false }}
            value={form.zalo_bot_token}
            onChange={setValue}
          />
          <SecretInput
            id="zalo_bot_webhook_secret"
            label="Webhook secret"
            status={settings?.zalo_bot_webhook_secret ?? { configured: false }}
            value={form.zalo_bot_webhook_secret}
            onChange={setValue}
          />
          <div className="space-y-2 md:col-span-2">
            <Label>API base</Label>
            <Input
              readOnly
              value={
                settings?.zalo_bot_api_base ??
                "https://bot-api.zaloplatforms.com"
              }
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <KeyRound className="size-4" />
            Official Account
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <Label htmlFor="zalo_oa_app_id">OA App ID</Label>
              <FieldStatus status={settings?.zalo_oa_app_id ?? { configured: false }} />
            </div>
            <Input
              id="zalo_oa_app_id"
              value={form.zalo_oa_app_id}
              onChange={(event) => setValue("zalo_oa_app_id", event.target.value)}
            />
          </div>
          <SecretInput
            id="zalo_oa_secret_key"
            label="OA secret key"
            status={settings?.zalo_oa_secret_key ?? { configured: false }}
            value={form.zalo_oa_secret_key}
            onChange={setValue}
          />
          <SecretInput
            id="zalo_oa_access_token"
            label="OA access token"
            status={settings?.zalo_oa_access_token ?? { configured: false }}
            value={form.zalo_oa_access_token}
            onChange={setValue}
          />
          <div className="space-y-2">
            <Label>API base</Label>
            <Input readOnly value={settings?.zalo_oa_api_base ?? "https://openapi.zalo.me"} />
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
