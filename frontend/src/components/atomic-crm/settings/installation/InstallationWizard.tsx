import { Check, ChevronLeft, ChevronRight, Loader2, RefreshCw, Save } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useInstallationContext } from "../../installation/installation-context";
import {
  finalizeInstallationSetupDraft,
  getInstallationAdminStatus,
  getInstallationCatalog,
  getInstallationSetupDraft,
  InstallationClientError,
  saveInstallationSetupDraft,
  type InstallationCatalog,
  type InstallationAdminStatus,
  type InstallationIssue,
  type InstallationSetupDraft,
  type InstallationSetupDraftPayload,
} from "../../installation/installation-client";
import {
  IdentityBrandingStep,
  KnowledgeTemplatesStep,
  PackCapabilitiesStep,
  PersonaStep,
  ProvidersIntegrationsStep,
  RegionalTerminologyStep,
  WorkflowStep,
} from "./steps/InstallationSteps";
import { describeInstallationIssue } from "./installation-issues";

const STEPS = [
  { key: "identity_branding", label: "Danh tính", title: "Danh tính và thương hiệu", description: "Thông tin hiển thị của khách hàng và màu sắc do quản trị viên nhập." },
  { key: "pack_capabilities", label: "Gói", title: "Gói ngành và chức năng", description: "Chọn gói cùng các chức năng được máy chủ công bố." },
  { key: "regional_terminology", label: "Khu vực", title: "Khu vực và thuật ngữ", description: "Ngôn ngữ, múi giờ, tiền tệ và cách gọi trong ngành." },
  { key: "workflow", label: "Quy trình", title: "Quy trình và bàn giao", description: "Chọn quy trình, cách chuyển cho nhân viên và chế độ tự động." },
  { key: "knowledge_templates", label: "Kiến thức", title: "Mẫu kiến thức", description: "Chọn phiên bản đã xuất bản hoặc tự tạo mẫu không có dữ liệu điền sẵn." },
  { key: "persona", label: "Agent", title: "Agent và chính sách", description: "Chọn phiên bản bất biến hoặc tạo Agent bằng nội dung của khách hàng." },
  { key: "providers_integrations", label: "Tích hợp", title: "Nhà cung cấp và tích hợp", description: "Lưu tham chiếu trong bản nháp; bí mật đi thẳng vào kho mã hóa." },
  { key: "review", label: "Rà soát", title: "Rà soát và xác nhận", description: "Kiểm tra xác thực phía máy chủ. Kích hoạt chỉ mở khi cơ chế thực thi runtime đã sẵn sàng." },
] as const;

type DraftSection = Exclude<(typeof STEPS)[number]["key"], "review">;

const sectionIssueMatches = (issue: InstallationIssue, section: DraftSection): boolean =>
  issue.path?.split(".").includes(section) ?? false;

const isSectionLocallyComplete = (
  section: DraftSection,
  payload: InstallationSetupDraftPayload,
  catalog: InstallationCatalog,
): boolean => {
  switch (section) {
    case "identity_branding":
      return Boolean(
        payload.identity_branding?.customer_identity.display_name.trim() &&
          payload.identity_branding.branding.app_name?.trim(),
      );
    case "regional_terminology": {
      const value = payload.regional_terminology;
      const pack = catalog.packs.find((item) => item.key === payload.pack_capabilities?.pack_key);
      return Boolean(
        value?.locale &&
          value.timezone.trim() &&
          value.currency &&
          (pack?.terminology_keys ?? []).every((key) => value.terminology[key]?.trim()),
      );
    }
    case "pack_capabilities":
      return Boolean(payload.pack_capabilities?.pack_key);
    case "workflow":
      return Boolean(payload.workflow?.workflow_policy.workflow_id);
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
  const { manifest, refreshRuntime } = useInstallationContext();
  const [draft, setDraft] = useState<InstallationSetupDraft | null>(null);
  const [catalog, setCatalog] = useState<InstallationCatalog | null>(null);
  const [adminStatus, setAdminStatus] = useState<InstallationAdminStatus | null>(null);
  const [payload, setPayload] = useState<InstallationSetupDraftPayload>({});
  const [currentStep, setCurrentStep] = useState(0);
  const [dirtySections, setDirtySections] = useState<Set<DraftSection>>(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<InstallationClientError | null>(null);
  const [finalizedRevisionId, setFinalizedRevisionId] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  const load = async () => {
    setLoading(true); setError(null); setConflict(null);
    try {
      const [nextDraft, nextCatalog, nextAdminStatus] = await Promise.all([
        getInstallationSetupDraft(),
        getInstallationCatalog(),
        getInstallationAdminStatus(),
      ]);
      setDraft(nextDraft); setPayload(nextDraft.payload); setCatalog(nextCatalog); setAdminStatus(nextAdminStatus); setDirtySections(new Set());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không tải được cấu hình thiết lập.");
    } finally { setLoading(false); }
  };

  useEffect(() => { void load(); }, []);
  useEffect(() => { if (!loading) headingRef.current?.focus(); }, [currentStep, loading]);

  const current = STEPS[currentStep];
  const section = current.key === "review" ? null : current.key;
  const currentIssues = useMemo(
    () => section && draft ? draft.issues.filter((issue) => sectionIssueMatches(issue, section)) : [],
    [draft, section],
  );

  const updateSection = <K extends DraftSection>(key: K, value: NonNullable<InstallationSetupDraftPayload[K]>) => {
    setPayload((currentPayload) => ({ ...currentPayload, [key]: value }));
    setDirtySections((currentDirty) => new Set(currentDirty).add(key));
    setConflict(null); setFinalizedRevisionId(null);
  };

  const updatePackSection = (value: NonNullable<InstallationSetupDraftPayload["pack_capabilities"]>) => {
    const allowedTerms = new Set(
      catalog?.packs.find((pack) => pack.key === value.pack_key)?.terminology_keys ?? [],
    );
    setPayload((currentPayload) => ({
      ...currentPayload,
      pack_capabilities: value,
      regional_terminology: currentPayload.regional_terminology
        ? {
            ...currentPayload.regional_terminology,
            terminology: Object.fromEntries(
              Object.entries(currentPayload.regional_terminology.terminology).filter(
                ([key]) => allowedTerms.has(key),
              ),
            ),
          }
        : undefined,
      workflow: undefined,
    }));
    setDirtySections((currentDirty) => {
      const next = new Set(currentDirty);
      next.add("pack_capabilities");
      next.add("regional_terminology");
      next.add("workflow");
      return next;
    });
    setConflict(null); setFinalizedRevisionId(null);
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
    if (!isSectionLocallyComplete(section, payload, catalog)) {
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

  const finalize = async () => {
    if (!draft) return;
    setSaving(true); setError(null);
    try {
      const revision = await finalizeInstallationSetupDraft({
        expectedDraftLockVersion: draft.lock_version,
        expectedInstallationLockVersion: draft.installation_lock_version,
      });
      setFinalizedRevisionId(revision.id);
      setAdminStatus((currentStatus) =>
        currentStatus
          ? { ...currentStatus, lifecycle: "VALIDATED" }
          : currentStatus,
      );
      await refreshRuntime();
    } catch (cause) {
      if (cause instanceof InstallationClientError) {
        setError(cause.message);
        if (cause.issues.length > 0) setDraft((currentDraft) => currentDraft ? { ...currentDraft, issues: cause.issues } : currentDraft);
      } else {
        setError(cause instanceof Error ? cause.message : "Không xác nhận được cấu hình.");
      }
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

  const completedCount = STEPS.slice(0, -1).filter((step) => draft.section_completion[step.key]).length;
  const allServerComplete = completedCount === STEPS.length - 1;
  const hasServerIssues = draft.issues.length > 0;
  const alreadyValidated = Boolean(
    adminStatus?.lifecycle === "VALIDATED" &&
      adminStatus.current_validation?.is_valid &&
      adminStatus.current_revision?.id === adminStatus.current_validation.revision_id,
  );

  return (
    <div className="grid gap-5 lg:grid-cols-[16rem_minmax(0,1fr)]">
      <aside className="min-w-0">
        <div className="sticky top-20 grid gap-3">
          <div className="rounded-lg border bg-card p-4">
            <p className="text-sm font-medium">Tiến độ máy chủ</p>
            <p className="mt-1 text-2xl font-semibold">{completedCount}/7</p>
            <p className="mt-1 text-xs text-muted-foreground">Trạng thái: {manifest.lifecycle}</p>
          </div>
          <nav aria-label="Các bước thiết lập" className="flex gap-2 overflow-x-auto pb-2 lg:grid lg:overflow-visible">
            {STEPS.map((step, index) => {
              const complete = step.key !== "review" && draft.section_completion[step.key];
              return (
                <button
                  key={step.key}
                  type="button"
                  className={cn(
                    "flex min-h-11 min-w-32 items-center gap-2 rounded-md border px-3 py-2 text-left text-sm transition-colors lg:min-w-0",
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

          {current.key === "identity_branding" ? <IdentityBrandingStep catalog={catalog} issues={currentIssues} value={payload.identity_branding} onChange={(value) => updateSection("identity_branding", value)} /> : null}
          {current.key === "regional_terminology" ? <RegionalTerminologyStep catalog={catalog} issues={currentIssues} selectedPackKey={payload.pack_capabilities?.pack_key} value={payload.regional_terminology} onChange={(value) => updateSection("regional_terminology", value)} /> : null}
          {current.key === "pack_capabilities" ? <PackCapabilitiesStep catalog={catalog} issues={currentIssues} value={payload.pack_capabilities} onChange={updatePackSection} /> : null}
          {current.key === "workflow" ? <WorkflowStep catalog={catalog} issues={currentIssues} selectedPackKey={payload.pack_capabilities?.pack_key} value={payload.workflow} onChange={(value) => updateSection("workflow", value)} /> : null}
          {current.key === "knowledge_templates" ? <KnowledgeTemplatesStep catalog={catalog} issues={currentIssues} value={payload.knowledge_templates} onChange={(value) => updateSection("knowledge_templates", value)} /> : null}
          {current.key === "persona" ? <PersonaStep catalog={catalog} issues={currentIssues} value={payload.persona} onChange={(value) => updateSection("persona", value)} /> : null}
          {current.key === "providers_integrations" ? <ProvidersIntegrationsStep catalog={catalog} issues={currentIssues} value={payload.providers_integrations} onChange={(value) => updateSection("providers_integrations", value)} /> : null}
          {current.key === "review" ? (
            <div className="grid gap-5">
              {draft.issues.length > 0 ? <Alert variant="destructive"><AlertTitle>Máy chủ còn phát hiện lỗi</AlertTitle><AlertDescription><ul className="list-disc space-y-1 pl-4">{draft.issues.map((issue, index) => <li key={`${issue.code}-${index}`}>{describeInstallationIssue(issue)}</li>)}</ul></AlertDescription></Alert> : <Alert><Check /><AlertTitle>Không có lỗi đã biết</AlertTitle><AlertDescription>{alreadyValidated ? "Phiên bản cấu hình hiện tại đã được máy chủ xác thực." : "Nhấn xác nhận để máy chủ kiểm tra lại toàn bộ và tạo phiên bản bất biến."}</AlertDescription></Alert>}
              <div className="grid gap-2 sm:grid-cols-2">{STEPS.slice(0, -1).map((step) => <div key={step.key} className="flex min-h-11 items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm"><span>{step.title}</span><span>{draft.section_completion[step.key] ? "Đã đạt" : "Chưa đạt"}</span></div>)}</div>
              <Alert><AlertTitle>Kiểm tra hội thoại an toàn</AlertTitle><AlertDescription>Tính năng thử không gửi ra ngoài chưa khả dụng cho đến khi cơ chế thực thi runtime được cài đặt và xác thực.</AlertDescription></Alert>
              {finalizedRevisionId ? <Alert><Check /><AlertTitle>Đã tạo phiên bản cấu hình</AlertTitle><AlertDescription>Mã phiên bản: {finalizedRevisionId}</AlertDescription></Alert> : null}
              <div className="grid gap-2 sm:grid-cols-2">
                <Button type="button" className="min-h-11" disabled={saving || !allServerComplete || hasServerIssues || alreadyValidated || finalizedRevisionId !== null} onClick={() => void finalize()}>{saving ? <Loader2 className="animate-spin" /> : <Save />}{alreadyValidated || finalizedRevisionId ? "Đã xác nhận" : "Xác nhận cấu hình"}</Button>
                <Button type="button" variant="outline" className="min-h-11" disabled>Kích hoạt chưa khả dụng cho đến khi runtime được xác thực</Button>
              </div>
            </div>
          ) : null}

          <div className="flex flex-col-reverse gap-2 border-t pt-5 sm:flex-row sm:justify-between">
            <Button type="button" variant="outline" className="min-h-11" disabled={currentStep === 0 || saving} onClick={() => navigateToStep(Math.max(0, currentStep - 1))}><ChevronLeft />Quay lại</Button>
            {section ? (
              <div className="flex flex-col gap-2 sm:flex-row">
                {dirtySections.has(section) ? <Button type="button" variant="ghost" className="min-h-11" disabled={saving} onClick={discardCurrentChanges}>Bỏ thay đổi</Button> : null}
                <Button type="button" variant="outline" className="min-h-11" disabled={saving || !dirtySections.has(section)} onClick={() => void saveCurrent()}>{saving ? <Loader2 className="animate-spin" /> : <Save />}Lưu bước</Button>
                <Button type="button" className="min-h-11" disabled={saving} onClick={() => void saveAndContinue()}>Lưu và tiếp tục<ChevronRight /></Button>
              </div>
            ) : null}
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
