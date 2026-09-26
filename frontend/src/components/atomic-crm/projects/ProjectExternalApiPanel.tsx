import { useEffect, useRef, useState } from "react";
import { AlertCircle, Info, Loader2, Plug, Save, Upload } from "lucide-react";
import { useNotify } from "ra-core";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

import type {
  ExternalApiFormState,
  ExternalApiView,
} from "./domain/external-api-contracts";
import {
  buildExternalApiPayload,
  emptyExternalApiForm,
  EXTERNAL_API_MAX_GUIDE_CHARS,
  formFromView,
  validateExternalApiForm,
} from "./domain/external-api-policy";
import {
  getProjectExternalApi,
  saveProjectExternalApi,
} from "./external-api-service";

/**
 * Per-project external API integration editor (admin only).
 *
 * The admin supplies the origin, the auth material (a write-only key) and the
 * vendor's own integration guide — pasted or uploaded from a file. The guide is
 * what the agent reads to decide which path to call; the base URL is the fixed
 * origin it may never leave.
 */
export const ProjectExternalApiPanel = ({ projectId }: { projectId: string }) => {
  const notify = useNotify();
  const fileInput = useRef<HTMLInputElement>(null);
  const [view, setView] = useState<ExternalApiView | null>(null);
  const [form, setForm] = useState<ExternalApiFormState>(emptyExternalApiForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getProjectExternalApi(projectId)
      .then((loaded) => {
        if (cancelled) return;
        setView(loaded);
        setForm(formFromView(loaded));
      })
      .catch(() => {
        if (cancelled) return;
        setView(null);
        setForm(emptyExternalApiForm());
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const errors = validateExternalApiForm(form);
  const baseUrlInvalid = errors.some(
    (error) => error.startsWith("Base URL") || error.startsWith("Chỉ dùng"),
  );
  const guideInvalid = errors.some((error) => error.startsWith("Hướng dẫn API"));

  // Mirrors the backend's composition (`f"{scheme} {key}".strip()`), with the
  // secret masked, so the admin sees exactly what the vendor will receive.
  const scheme = form.auth_scheme.trim();
  const headerName = form.auth_header.trim();
  const headerPreview = headerName
    ? `${headerName}: ${scheme ? `${scheme} ` : ""}•••`
    : "không gửi header xác thực";

  const keyStatus = form.clear_api_key
    ? "Sẽ xóa khóa khi lưu"
    : form.api_key.trim()
      ? "Khóa mới sẽ được lưu"
      : view?.api_key.configured
        ? `Đã lưu · ${view.api_key.preview ?? ""}`
        : "Chưa cấu hình";

  const save = async () => {
    setSaving(true);
    try {
      const saved = await saveProjectExternalApi(
        projectId,
        buildExternalApiPayload(form),
      );
      setView(saved);
      setForm(formFromView(saved));
      notify("Đã lưu tích hợp API ngoài.", { type: "success" });
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setSaving(false);
    }
  };

  const loadGuideFile = async (file: File | undefined) => {
    if (!file) return;
    try {
      const text = await file.text();
      setForm((current) => ({ ...current, guide: text }));
      notify(`Đã đọc ${file.name}. Nhấn Lưu để áp dụng.`, { type: "info" });
    } catch {
      notify("Không đọc được tệp hướng dẫn.", { type: "error" });
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  if (loading) {
    return (
      <div
        className="overflow-hidden rounded-lg border border-border bg-card shadow-xs"
        data-testid="project-external-api"
      >
        <div className="flex items-center gap-2 border-b border-border bg-muted/30 px-4 py-3">
          <Skeleton className="size-4 rounded-full" />
          <Skeleton className="h-4 w-44" />
        </div>
        <div className="space-y-4 p-4">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-44 w-full" />
        </div>
      </div>
    );
  }

  return (
    <div
      className="overflow-hidden rounded-lg border border-border bg-card shadow-xs"
      data-testid="project-external-api"
    >
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-border bg-muted/30 px-4 py-3">
        <div className="flex items-center gap-2">
          <Plug className="size-4 text-primary" aria-hidden="true" />
          <h4 className="text-body font-semibold">API ngoài của dự án</h4>
        </div>
        <label className="inline-flex cursor-pointer items-center gap-2 text-body-sm text-muted-foreground">
          <Switch
            checked={form.enabled}
            onCheckedChange={(checked) =>
              setForm((current) => ({ ...current, enabled: checked }))
            }
            aria-label="Bật tích hợp API"
          />
          Bật tích hợp API
        </label>
      </div>

      <div className="space-y-5 p-4">
        <p className="max-w-3xl text-body-sm text-muted-foreground">
          Chatbot chỉ gọi được hệ thống ngoài trên Base URL bên dưới, theo đúng
          hướng dẫn bạn dán vào đây. Base URL và khóa API không bao giờ được gửi
          cho chatbot.
        </p>

        {!form.enabled && (
          <Alert variant="info">
            <Info aria-hidden="true" />
            <AlertDescription>
              Tích hợp đang tắt. Chatbot sẽ không gọi API ngoài của dự án này.
            </AlertDescription>
          </Alert>
        )}

        <div className="space-y-2">
          <Label htmlFor="external-api-base-url">Base URL</Label>
          <Input
            id="external-api-base-url"
            inputMode="url"
            value={form.base_url}
            placeholder="https://api.example.com"
            aria-invalid={baseUrlInvalid}
            aria-describedby={baseUrlInvalid ? "external-api-errors" : undefined}
            onChange={(event) =>
              setForm((current) => ({ ...current, base_url: event.target.value }))
            }
          />
        </div>

        <div className="grid gap-x-4 gap-y-5 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="external-api-auth-header">
              Tên header xác thực
            </Label>
            <Input
              id="external-api-auth-header"
              value={form.auth_header}
              placeholder="X-API-Key"
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  auth_header: event.target.value,
                }))
              }
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="external-api-auth-scheme">Tiền tố xác thực</Label>
            <Input
              id="external-api-auth-scheme"
              value={form.auth_scheme}
              placeholder="Bearer"
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  auth_scheme: event.target.value,
                }))
              }
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-body-sm text-muted-foreground">
          <span>Chatbot sẽ gửi header</span>
          <code
            className="rounded-md border border-border bg-muted/30 px-1.5 py-0.5 font-mono text-helper text-foreground"
            data-testid="project-external-api-header-preview"
          >
            {headerPreview}
          </code>
          <span>— để trống tiền tố nếu API nhận khóa trực tiếp.</span>
        </div>

        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Label htmlFor="external-api-key">Khóa API</Label>
            <div className="flex items-center gap-2">
              <span
                className="text-body-sm text-muted-foreground"
                data-testid="project-external-api-key-status"
              >
                {keyStatus}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className={
                  form.clear_api_key
                    ? undefined
                    : "text-destructive hover:text-destructive"
                }
                onClick={() =>
                  setForm((current) =>
                    current.clear_api_key
                      ? { ...current, clear_api_key: false }
                      : { ...current, api_key: "", clear_api_key: true },
                  )
                }
              >
                {form.clear_api_key ? "Hoàn tác" : "Xóa khóa"}
              </Button>
            </div>
          </div>
          <Input
            id="external-api-key"
            type="password"
            autoComplete="off"
            value={form.api_key}
            placeholder="Để trống nếu không đổi cấu hình"
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                api_key: event.target.value,
                clear_api_key: false,
              }))
            }
          />
        </div>

        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Label htmlFor="external-api-guide">Hướng dẫn API cho chatbot</Label>
            <div className="flex items-center gap-2">
              <span
                className={
                  guideInvalid
                    ? "text-body-sm text-destructive"
                    : "text-body-sm text-muted-foreground"
                }
                data-testid="project-external-api-guide-count"
              >
                {form.guide.length}/{EXTERNAL_API_MAX_GUIDE_CHARS} ký tự
              </span>
              <input
                ref={fileInput}
                type="file"
                className="hidden"
                aria-label="Tệp hướng dẫn"
                accept=".md,.markdown,.txt,text/markdown,text/plain"
                onChange={(event) => void loadGuideFile(event.target.files?.[0])}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                data-testid="project-external-api-upload"
                onClick={() => fileInput.current?.click()}
              >
                <Upload className="size-3.5" />
                Tải tệp lên
              </Button>
            </div>
          </div>
          <Textarea
            id="external-api-guide"
            aria-label="Hướng dẫn API cho chatbot"
            // ``field-sizing-content`` (the shared Textarea default) grows with
            // the value; an 8 KB guide would then stretch the whole panel to
            // screen-length, so pin a scrollable height the admin can drag.
            className="field-sizing-fixed h-[14rem] max-h-[36rem] resize-y font-mono text-body-sm leading-relaxed sm:h-[20rem]"
            value={form.guide}
            placeholder={
              "# Hướng dẫn tích hợp API cho Chatbot\n\n" +
              "POST /api/v1/integration/password-reset/otp\n" +
              "Tham số: phone (số điện thoại)."
            }
            aria-invalid={guideInvalid}
            aria-describedby={guideInvalid ? "external-api-errors" : undefined}
            onChange={(event) =>
              setForm((current) => ({ ...current, guide: event.target.value }))
            }
          />
          <p className="text-body-sm text-muted-foreground">
            Dán hướng dẫn tích hợp API (Markdown hoặc văn bản), hoặc tải lên tệp
            .md. Chatbot đọc phần này để biết cần gọi endpoint nào và truyền tham
            số gì.
          </p>
        </div>

        {errors.length > 0 && (
          <Alert
            variant="destructive"
            id="external-api-errors"
            data-testid="project-external-api-errors"
          >
            <AlertCircle aria-hidden="true" />
            <AlertTitle>Chưa lưu được</AlertTitle>
            <AlertDescription>
              <ul className="space-y-1">
                {errors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-border bg-muted/30 px-4 py-3">
        <Button
          type="button"
          size="sm"
          data-testid="project-external-api-save"
          disabled={saving || errors.length > 0}
          onClick={() => void save()}
        >
          {saving ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Save className="size-4" />
          )}
          {saving ? "Đang lưu…" : "Lưu"}
        </Button>
      </div>
    </div>
  );
};
