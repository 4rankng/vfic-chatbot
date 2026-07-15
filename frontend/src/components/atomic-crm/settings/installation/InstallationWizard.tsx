import { Check, ChevronLeft, ChevronRight, Loader2, RefreshCw, Save } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  getInstallationCatalog,
  getInstallationSetupDraft,
  InstallationClientError,
  saveInstallationSetupDraft,
  type InstallationCatalog,
  type InstallationIssue,
  type InstallationSetupDraft,
  type InstallationSetupDraftPayload,
} from "../../installation/installation-client";
import { KnowledgeTemplatesStep, PersonaStep, ProvidersIntegrationsStep } from "./steps/InstallationSteps";

const STEPS = [
  { key: "providers_integrations", label: "Kết nối AI", title: "Kết nối AI", description: "Chọn nhà cung cấp, model và lưu khóa API trong kho mã hóa." },
  { key: "persona", label: "Agent", title: "Agent", description: "Thiết lập giọng điệu và nguyên tắc trả lời của chatbot." },
  { key: "knowledge_templates", label: "Kiến thức", title: "Kiến thức", description: "Thêm tài liệu và cấu trúc dữ liệu riêng khi chatbot cần trả lời dựa trên nguồn của bạn." },
] as const;

type DraftSection = (typeof STEPS)[number]["key"];

const sectionIssueMatches = (issue: InstallationIssue, section: DraftSection): boolean =>
  issue.path?.split(".").includes(section) ?? false;

const isSectionLocallyComplete = (
  section: DraftSection,
  payload: InstallationSetupDraftPayload,
): boolean => {
  switch (section) {
    case "knowledge_templates":
      return (payload.knowledge_templates?.template_version_refs.length ?? 0) > 0;
    case "persona":
      return Boolean(payload.persona?.persona_version_id && payload.persona.checksum);
    case "providers_integrations": {
      const policy = payload.providers_integrations?.provider_policy;
      return Boolean(
        policy?.chat_integration_key &&
          policy.chat_model.trim() &&
          policy.embedding_model.trim() &&
          policy.temperature >= 0 &&
          policy.temperature <= 2 &&
          policy.max_output_tokens > 0,
      );
    }
  }
};

const Loading = () => (
  <div className="flex min-h-64 items-center justify-center gap-3" aria-live="polite">
    <Loader2 className="size-6 animate-spin" aria-hidden="true" />
    <span>Đang tải bản nháp từ máy chủ</span>
  </div>
);

export const InstallationWizard = () => {
  const [draft, setDraft] = useState<InstallationSetupDraft | null>(null);
  const [catalog, setCatalog] = useState<InstallationCatalog | null>(null);
  const [payload, setPayload] = useState<InstallationSetupDraftPayload>({});
  const [currentStep, setCurrentStep] = useState(0);
  const [dirtySections, setDirtySections] = useState<Set<DraftSection>>(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<InstallationClientError | null>(null);
  const [showConfiguration, setShowConfiguration] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  const load = async () => {
    setLoading(true); setError(null); setConflict(null);
    try {
      const [nextDraft, nextCatalog] = await Promise.all([
        getInstallationSetupDraft(),
        getInstallationCatalog(),
      ]);
      setDraft(nextDraft); setPayload(nextDraft.payload); setCatalog(nextCatalog); setDirtySections(new Set());
      setShowConfiguration(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không tải được cấu hình thiết lập.");
    } finally { setLoading(false); }
  };

  useEffect(() => { void load(); }, []);
  useEffect(() => { if (!loading) headingRef.current?.focus(); }, [currentStep, loading]);

  const current = STEPS[currentStep];
  const section = current.key;
  const currentIssues = useMemo(
    () => section && draft ? draft.issues.filter((issue) => sectionIssueMatches(issue, section)) : [],
    [draft, section],
  );

  const updateSection = <K extends DraftSection>(key: K, value: NonNullable<InstallationSetupDraftPayload[K]>) => {
    setPayload((currentPayload) => ({ ...currentPayload, [key]: value }));
    setDirtySections((currentDirty) => new Set(currentDirty).add(key));
    setConflict(null);
  };

  const navigateToStep = (nextStep: number) => {
    if (section && dirtySections.has(section)) {
      setError("Hãy lưu hoặc bỏ thay đổi của bước hiện tại trước khi chuyển bước.");
      headingRef.current?.focus();
      return;
    }
    setError(null);
    setCurrentStep(nextStep);
  };

  const discardCurrentChanges = () => {
    if (!section || !draft) return;
    setPayload((currentPayload) => {
      const next = { ...currentPayload };
      const persisted = draft.payload[section];
      if (persisted === undefined) delete next[section];
      else Object.assign(next, { [section]: persisted });
      return next;
    });
    setDirtySections((currentDirty) => {
      const next = new Set(currentDirty);
      next.delete(section);
      return next;
    });
    setError(null); setConflict(null);
  };

  const saveCurrent = async (): Promise<boolean> => {
    if (!draft || !catalog || !section) return false;
    if (!isSectionLocallyComplete(section, payload)) {
      setError("Bước này chưa đủ thông tin bắt buộc. Không có giá trị mặc định được tự thêm.");
      headingRef.current?.focus();
      return false;
    }
    setSaving(true); setError(null); setConflict(null);
    try {
      const next = await saveInstallationSetupDraft(payload, draft.lock_version);
      setDraft(next); setPayload(next.payload); setDirtySections(new Set());
      return true;
    } catch (cause) {
      if (cause instanceof InstallationClientError && cause.code === "INSTALLATION_CONFLICT") {
        setConflict(cause);
      } else {
        setError(cause instanceof Error ? cause.message : "Không lưu được bản nháp.");
        if (cause instanceof InstallationClientError && cause.issues.length > 0) {
          setDraft((currentDraft) =>
            currentDraft ? { ...currentDraft, issues: cause.issues } : currentDraft,
          );
        }
        headingRef.current?.focus();
      }
      return false;
    } finally { setSaving(false); }
  };

  const saveAndContinue = async () => {
    if (await saveCurrent()) setCurrentStep((index) => Math.min(index + 1, STEPS.length - 1));
  };

  const mergeAfterConflict = async () => {
    setSaving(true); setError(null);
    try {
      const latest = await getInstallationSetupDraft();
      const merged = structuredClone(latest.payload);
      for (const key of dirtySections) {
        const localSection = payload[key];
        if (localSection === undefined) delete merged[key];
        else Object.assign(merged, { [key]: localSection });
      }
      const saved = await saveInstallationSetupDraft(merged, latest.lock_version);
      setDraft(saved); setPayload(saved.payload); setDirtySections(new Set()); setConflict(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không áp dụng lại được thay đổi.");
    } finally { setSaving(false); }
  };

  if (loading) return <Loading />;
  if (!draft || !catalog) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Không tải được thiết lập</AlertTitle>
        <AlertDescription className="gap-4"><p>{error ?? "Máy chủ chưa trả về bản nháp hợp lệ."}</p><Button type="button" variant="outline" className="min-h-11" onClick={() => void load()}><RefreshCw />Thử lại</Button></AlertDescription>
      </Alert>
    );
  }

  const openConfiguration = (step: DraftSection) => {
    setCurrentStep(STEPS.findIndex((item) => item.key === step));
    setShowConfiguration(true);
  };

  if (!showConfiguration) {
    return (
      <div className="mx-auto grid max-w-4xl gap-5">
        <Card>
          <CardHeader>
            <CardTitle className="text-2xl sm:text-3xl">Thiết lập chatbot khi sẵn sàng</CardTitle>
            <CardDescription className="max-w-2xl text-base leading-7">
              Không có chatbot nào được bật khi cài đặt mới. Khi cần, chỉ cấu hình ba phần: kết nối AI, Agent và kiến thức.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Alert>
              <Check />
              <AlertTitle>Không có việc bắt buộc lúc khởi tạo</AlertTitle>
              <AlertDescription>
                Chatbot vẫn tắt an toàn cho đến khi bạn lưu đủ ba phần này và chủ động bật nó sau này.
              </AlertDescription>
            </Alert>
          </CardContent>
        </Card>
        <div className="grid gap-4 sm:grid-cols-2">
          {[
            { step: "providers_integrations" as const, title: "Kết nối AI", description: "Lưu khóa API, chọn nhà cung cấp và model." },
            { step: "persona" as const, title: "Agent", description: "Thiết lập giọng điệu và nguyên tắc trả lời." },
            { step: "knowledge_templates" as const, title: "Kiến thức", description: "Thêm tài liệu và cấu trúc dữ liệu của riêng bạn." },
          ].map((item) => (
            <Card key={item.step} className="flex min-h-44 flex-col">
              <CardHeader className="flex-1">
                <CardTitle className="text-lg">{item.title}</CardTitle>
                <CardDescription className="leading-6">{item.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <Button type="button" variant="outline" onClick={() => openConfiguration(item.step)}>
                  Thiết lập {item.title}
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[16rem_minmax(0,1fr)]">
      <aside className="min-w-0">
        <div className="sticky top-20 grid gap-3">
          <div className="rounded-lg border bg-card p-4">
            <p className="text-sm font-medium">Thiết lập tùy chọn</p>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">Chỉ mở mục phù hợp với nhu cầu hiện tại của bạn.</p>
            <Button type="button" variant="ghost" className="mt-2 justify-start px-0" onClick={() => setShowConfiguration(false)}>Về tổng quan</Button>
          </div>
          <nav
            aria-label="Các bước thiết lập"
            className="grid grid-cols-1 gap-2 sm:grid-cols-3"
          >
            {STEPS.map((step, index) => {
              const complete = draft.section_completion[step.key];
              return (
                <button
                  key={step.key}
                  type="button"
                  className={cn(
                    "flex min-h-11 min-w-0 items-center gap-2 rounded-md border px-3 py-2 text-left text-sm transition-colors",
                    currentStep === index ? "border-primary bg-primary text-primary-foreground" : "bg-card hover:bg-muted",
                  )}
                  aria-current={currentStep === index ? "step" : undefined}
                  onClick={() => navigateToStep(index)}
                >
                  <span className="flex size-6 shrink-0 items-center justify-center rounded-full border text-xs">{complete ? <Check className="size-3" /> : index + 1}</span>
                  <span className="truncate">{step.label}</span>
                </button>
              );
            })}
          </nav>
        </div>
      </aside>

      <Card className="min-w-0 bg-card">
        <CardHeader className="border-b">
          <CardTitle ref={headingRef} tabIndex={-1} className="text-xl outline-none sm:text-2xl">{current.title}</CardTitle>
          <CardDescription className="leading-6">{current.description}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-6 pt-0">
          {error ? <Alert variant="destructive"><AlertTitle>Không thể tiếp tục</AlertTitle><AlertDescription>{error}</AlertDescription></Alert> : null}
          {conflict ? (
            <Alert variant="destructive">
              <AlertTitle>Bản nháp đã được thay đổi ở nơi khác</AlertTitle>
              <AlertDescription className="gap-3">
                <p>Thay đổi chưa lưu của bạn vẫn được giữ trong trang này.</p>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Button type="button" variant="outline" className="min-h-11" disabled={saving} onClick={() => void load()}>Tải bản mới</Button>
                  <Button type="button" className="min-h-11" disabled={saving} onClick={() => void mergeAfterConflict()}>Áp dụng lại phần đã sửa</Button>
                </div>
              </AlertDescription>
            </Alert>
          ) : null}

          {current.key === "knowledge_templates" ? <KnowledgeTemplatesStep catalog={catalog} issues={currentIssues} value={payload.knowledge_templates} onChange={(value) => updateSection("knowledge_templates", value)} /> : null}
          {current.key === "persona" ? <PersonaStep catalog={catalog} issues={currentIssues} value={payload.persona} onChange={(value) => updateSection("persona", value)} /> : null}
          {current.key === "providers_integrations" ? <ProvidersIntegrationsStep catalog={catalog} issues={currentIssues} value={payload.providers_integrations} onChange={(value) => updateSection("providers_integrations", value)} /> : null}

          <div className="flex flex-col-reverse gap-2 border-t pt-5 sm:flex-row sm:justify-between">
            <Button type="button" variant="outline" className="min-h-11" disabled={currentStep === 0 || saving} onClick={() => navigateToStep(Math.max(0, currentStep - 1))}><ChevronLeft />Quay lại</Button>
            <div className="flex flex-col gap-2 sm:flex-row">
              {dirtySections.has(section) ? <Button type="button" variant="ghost" className="min-h-11" disabled={saving} onClick={discardCurrentChanges}>Bỏ thay đổi</Button> : null}
              <Button type="button" variant="outline" className="min-h-11" disabled={saving || !dirtySections.has(section)} onClick={() => void saveCurrent()}>{saving ? <Loader2 className="animate-spin" /> : <Save />}Lưu</Button>
              <Button type="button" className="min-h-11" disabled={saving} onClick={() => void saveAndContinue()}>Lưu và tiếp tục<ChevronRight /></Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
