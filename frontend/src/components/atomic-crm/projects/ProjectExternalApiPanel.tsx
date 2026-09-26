import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { AlertCircle, Info, Loader2, Plug, Save, Upload } from "lucide-react";
import { useNotify } from "ra-core";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

import type {
  ExternalApiFormState,
  ExternalApiTestResult,
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
  testProjectExternalApi,
} from "./external-api-service";

/** Stable readiness blocker codes → the chip's Vietnamese labels. */
const BLOCKER_LABELS: Record<string, string> = {
  integration_disabled: "Tích hợp đang tắt",
  project_inactive: "Dự án đang tắt",
  knowledge_capability_missing: "Agent chưa có quyền tri thức",
  persona_missing: "Agent chưa có persona",
  installation_required: "Chưa có bản cài đặt Agent hoạt động",
  readiness_unavailable: "Không kiểm tra được trạng thái Agent",
};

type TestOutcome = {
  variant: "info" | "warning" | "destructive";
  title: string;
  body: ReactNode;
};

/** Map one test-call state onto the alert that explains it to the admin. */
const formatTestResult = (result: ExternalApiTestResult): TestOutcome => {
  switch (result.state) {
    case "ok":
      return {
        variant: "info",
        title: `Thành công · HTTP ${result.status_code}`,
        body: (
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/40 p-2 font-mono text-helper">
            {result.text}
          </pre>
        ),
      };
    case "rate_limited":
      return {
        variant: "warning",
        title: "Bị chặn thử lại",
        body: "Từ chối gửi trùng trong 1 phút — đúng như chatbot gặp phải.",
      };
    case "not_configured":
      return {
        variant: "warning",
        title: "Chưa cấu hình",
        body: "Tích hợp đang tắt hoặc dự án đang tắt, nên không có gì để gọi.",
      };
    case "invalid_request":
      return {
        variant: "warning",
        title: "Yêu cầu không hợp lệ",
        body: result.detail,
      };
    case "error":
      return {
        variant: "destructive",
        title: `Lỗi${result.status_code ? ` · HTTP ${result.status_code}` : ""}`,
        body: result.detail,
      };
    default:
      return {
        variant: "destructive",
        title: "Không gọi được",
        body: result.detail,
      };
  }
};

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
  const [testMethod, setTestMethod] = useState<"GET" | "POST">("GET");
  const [testPath, setTestPath] = useState("");
  const [testParams, setTestParams] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ExternalApiTestResult | null>(null);

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

  // The params field is a JSON object literal; anything else is a typo the
  // admin must fix before the probe can fire.
  let paramsError: string | null = null;
  let parsedParams: Record<string, unknown> | null = null;
  if (testParams.trim() !== "") {
    try {
      const parsed: unknown = JSON.parse(testParams);
      if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
        parsedParams = parsed as Record<string, unknown>;
      } else {
        paramsError = "Tham số phải là JSON object";
      }
    } catch {
      paramsError = "Tham số phải là JSON object";
    }
  }

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

  const runTest = async () => {
    setTesting(true);
    try {
      const result = await testProjectExternalApi(projectId, {
        method: testMethod,
        path: testPath.trim(),
        ...(parsedParams ? { params: parsedParams } : {}),
      });
      setTestResult(result);
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setTesting(false);
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

  const testOutcome = testResult ? formatTestResult(testResult) : null;

  return (
    <Card
      data-testid="project-external-api"
      className="overflow-hidden rounded-lg border border-border bg-card shadow-xs"
    >
      <CardHeader className="border-b border-border bg-muted/30 py-4">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          <div className="flex items-center gap-3">
            <span
              className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary"
              aria-hidden="true"
            >
              <Plug className="size-4" aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <CardTitle className="text-body">API ngoài của dự án</CardTitle>
              <p className="text-body-sm text-muted-foreground">
                Chatbot chỉ gọi được hệ thống ngoài trên Base URL bên dưới, theo
                đúng hướng dẫn bạn dán vào đây. Base URL và khóa API không bao
                giờ được gửi cho chatbot.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {view ? (
              <Badge
                data-testid="project-external-api-readiness"
                variant={
                  view.chatbot_readiness.ready ? "secondary" : "outline"
                }
              >
                {view.chatbot_readiness.ready
                  ? "Chatbot sẵn sàng gọi API"
                  : `Chưa sẵn sàng · ${view.chatbot_readiness.blockers
                      .map((code) => BLOCKER_LABELS[code] ?? code)
                      .join("; ")}`}
              </Badge>
            ) : null}
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
        </div>
      </CardHeader>

      <CardContent className="px-0 py-0">
        <section className="grid gap-3 px-6 py-5">
          <h5 className="text-section-title">Kết nối</h5>
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
          <p className="text-body-sm text-muted-foreground">
            Chatbot chỉ gọi origin này. Bắt buộc https; http chỉ hợp lệ với
            127.0.0.1/localhost.
          </p>
        </section>

        <div className="border-t border-border" />

        <section className="grid gap-3 px-6 py-5">
          <h5 className="text-section-title">Xác thực</h5>
          <div className="grid gap-x-4 gap-y-3 sm:grid-cols-2">
            <div className="grid gap-2">
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
            <div className="grid gap-2">
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
        </section>

        <div className="border-t border-border" />

        <section className="grid gap-3 px-6 py-5">
          <h5 className="text-section-title">Khóa API</h5>
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
          <p className="text-body-sm text-muted-foreground">
            Khóa được niêm phong và chỉ dùng cho lời gọi của chatbot. Để trống
            nếu không đổi cấu hình.
          </p>
        </section>

        <div className="border-t border-border" />

        <section className="grid gap-3 px-6 py-5">
          <h5 className="text-section-title">Hướng dẫn API cho chatbot</h5>
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
        </section>

        <div className="border-t border-border" />

        <section className="grid gap-3 px-6 py-5">
          <h5 className="text-section-title">Gửi thử</h5>
          <Label>Gửi thử lời gọi</Label>
          <p className="text-body-sm text-muted-foreground">
            Gửi một lời gọi thật qua đúng đường mà chatbot dùng: cùng khóa, cùng
            header, cùng luật chống gửi trùng.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Method"
              value={testMethod}
              onChange={(event) =>
                setTestMethod(event.target.value === "POST" ? "POST" : "GET")
              }
              className="h-10 w-24 rounded-md border border-border bg-background px-3 text-control outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]"
            >
              <option value="GET">GET</option>
              <option value="POST">POST</option>
            </select>
            <Input
              aria-label="Đường dẫn thử"
              placeholder="/api/v1/integration/password-reset/otp"
              value={testPath}
              onChange={(event) => setTestPath(event.target.value)}
              className="min-w-40 flex-1"
            />
            <Input
              aria-label="Tham số JSON"
              placeholder='{"phone":"0900000000"}'
              value={testParams}
              onChange={(event) => setTestParams(event.target.value)}
              aria-invalid={paramsError !== null}
              aria-describedby={
                paramsError !== null ? "external-api-test-params-error" : undefined
              }
              className="min-w-40 flex-1"
            />
            <Button
              type="button"
              data-testid="project-external-api-test"
              disabled={testing || !testPath.trim() || paramsError !== null}
              onClick={() => void runTest()}
            >
              {testing ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Plug className="size-4" />
              )}
              {testing ? "Đang gửi…" : "Gửi thử"}
            </Button>
          </div>
          {paramsError !== null && (
            <p
              id="external-api-test-params-error"
              className="text-body-sm text-destructive"
            >
              {paramsError}
            </p>
          )}
          {testOutcome !== null && (
            <Alert
              variant={testOutcome.variant}
              data-testid="project-external-api-test-result"
            >
              {testOutcome.variant === "info" ? (
                <Info aria-hidden="true" />
              ) : (
                <AlertCircle aria-hidden="true" />
              )}
              <AlertTitle>{testOutcome.title}</AlertTitle>
              <AlertDescription>{testOutcome.body}</AlertDescription>
            </Alert>
          )}
        </section>

        {errors.length > 0 && (
          <div className="px-6 py-4">
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
          </div>
        )}
      </CardContent>

      <div className="flex items-center justify-end gap-2 border-t border-border bg-muted/30 px-6 py-4">
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
    </Card>
  );
};
