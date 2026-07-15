import { ChevronLeft, ChevronRight, Loader2, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { KnowledgeUpload } from "@/components/atomic-crm/knowledge/KnowledgeUpload";
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
import { SetupStepper } from "./SetupStepper";
import {
  PackCapabilitiesStep,
  PersonaStep,
  ProvidersIntegrationsStep,
} from "./steps/InstallationSteps";

const STEPS = [
  {
    key: "pack_capabilities",
    label: "Loại hình",
    title: "Chọn loại hình hoạt động",
    description:
      "Chọn trước để hệ thống dùng đúng chức năng, dữ liệu và quy trình cho sản phẩm của bạn.",
  },
  {
    key: "providers_integrations",
    label: "Kết nối AI",
    title: "Kết nối AI",
    description: "Chọn nhà cung cấp, model và lưu khóa API trong kho mã hóa.",
  },
  {
    key: "persona",
    label: "Agent",
    title: "Agent",
    description: "Thiết lập giọng điệu và nguyên tắc trả lời của chatbot.",
  },
  {
    key: "knowledge_templates",
    label: "Kiến thức",
    title: "Kiến thức",
    description:
      "Thêm tài liệu và cấu trúc dữ liệu riêng khi chatbot cần trả lời dựa trên nguồn của bạn.",
  },
] as const;

type DraftSection = (typeof STEPS)[number]["key"];

const sectionIssueMatches = (
  issue: InstallationIssue,
  section: DraftSection,
): boolean => issue.path?.split(".").includes(section) ?? false;

const isSectionLocallyComplete = (
  section: DraftSection,
  payload: InstallationSetupDraftPayload,
): boolean => {
  switch (section) {
    case "pack_capabilities":
      return Boolean(payload.pack_capabilities?.pack_key);
    case "knowledge_templates":
      return true;
    case "persona":
      return Boolean(
        payload.persona?.persona_version_id && payload.persona.checksum,
      );
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
  <div
    className="flex min-h-64 items-center justify-center gap-3 text-body text-muted-foreground"
    aria-live="polite"
  >
    <Loader2 className="size-6 animate-spin" aria-hidden="true" />
    <span>Đang tải bản nháp từ máy chủ</span>
  </div>
);

export const InstallationWizard = () => {
  const [draft, setDraft] = useState<InstallationSetupDraft | null>(null);
  const [catalog, setCatalog] = useState<InstallationCatalog | null>(null);
  const [payload, setPayload] = useState<InstallationSetupDraftPayload>({});
  const [currentStep, setCurrentStep] = useState(0);
  const [dirtySections, setDirtySections] = useState<Set<DraftSection>>(
    new Set(),
  );
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<InstallationClientError | null>(
    null,
  );
  const [knowledgeUploadOpen, setKnowledgeUploadOpen] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const saveProviderSecretsRef = useRef<(() => Promise<boolean>) | null>(null);
  const savePersonaRef = useRef<
    (() => Promise<InstallationSetupDraftPayload["persona"] | null>) | null
  >(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    setConflict(null);
    try {
      const [nextDraft, nextCatalog] = await Promise.all([
        getInstallationSetupDraft(),
        getInstallationCatalog(),
      ]);
      setDraft(nextDraft);
      setPayload(nextDraft.payload);
      setCatalog(nextCatalog);
      setDirtySections(new Set());
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Không tải được cấu hình thiết lập.",
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);
  useEffect(() => {
    if (!loading) headingRef.current?.focus();
  }, [currentStep, loading]);

  const current = STEPS[currentStep];
  const section = current.key;
  const currentIssues = useMemo(
    () =>
      section && draft
        ? draft.issues.filter((issue) => sectionIssueMatches(issue, section))
        : [],
    [draft, section],
  );

  const updateSection = <K extends DraftSection>(
    key: K,
    value: NonNullable<InstallationSetupDraftPayload[K]>,
  ) => {
    setPayload((currentPayload) => ({ ...currentPayload, [key]: value }));
    setDirtySections((currentDirty) => new Set(currentDirty).add(key));
    setConflict(null);
  };

  const navigateToStep = (nextStep: number) => {
    if (section && dirtySections.has(section)) {
      setError(
        "Hãy lưu hoặc bỏ thay đổi của bước hiện tại trước khi chuyển bước.",
      );
      headingRef.current?.focus();
      return;
    }
    if (
      STEPS[nextStep]?.key === "knowledge_templates" &&
      !draft?.section_completion.pack_capabilities
    ) {
      setError("Chọn loại hình hoạt động trước khi thêm tài liệu.");
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
    setError(null);
    setConflict(null);
  };

  const saveCurrent = async (payloadToSave = payload): Promise<boolean> => {
    if (!draft || !catalog || !section) return false;
    if (!isSectionLocallyComplete(section, payloadToSave)) {
      setError(
        "Bước này chưa đủ thông tin bắt buộc. Không có giá trị mặc định được tự thêm.",
      );
      headingRef.current?.focus();
      return false;
    }
    setSaving(true);
    setError(null);
    setConflict(null);
    try {
      const next = await saveInstallationSetupDraft(
        payloadToSave,
        draft.lock_version,
      );
      setDraft(next);
      setPayload(next.payload);
      setDirtySections(new Set());
      return true;
    } catch (cause) {
      if (
        cause instanceof InstallationClientError &&
        cause.code === "INSTALLATION_CONFLICT"
      ) {
        setConflict(cause);
      } else {
        setError(
          cause instanceof Error ? cause.message : "Không lưu được bản nháp.",
        );
        if (
          cause instanceof InstallationClientError &&
          cause.issues.length > 0
        ) {
          setDraft((currentDraft) =>
            currentDraft
              ? { ...currentDraft, issues: cause.issues }
              : currentDraft,
          );
        }
        headingRef.current?.focus();
      }
      return false;
    } finally {
      setSaving(false);
    }
  };

  const registerProviderSecretSaver = useCallback(
    (save: (() => Promise<boolean>) | null) => {
      saveProviderSecretsRef.current = save;
    },
    [],
  );

  const registerPersonaSaver = useCallback(
    (
      save:
        (() => Promise<InstallationSetupDraftPayload["persona"] | null>) | null,
    ) => {
      savePersonaRef.current = save;
    },
    [],
  );

  const saveAndContinue = async () => {
    if (
      section === "providers_integrations" &&
      saveProviderSecretsRef.current &&
      !(await saveProviderSecretsRef.current())
    ) {
      headingRef.current?.focus();
      return;
    }
    const createdPersona =
      section === "persona" ? await savePersonaRef.current?.() : null;
    if (
      section === "persona" &&
      savePersonaRef.current &&
      !createdPersona &&
      !payload.persona
    ) {
      headingRef.current?.focus();
      return;
    }
    const payloadToSave = createdPersona
      ? { ...payload, persona: createdPersona }
      : payload;
    if (await saveCurrent(payloadToSave))
      setCurrentStep((index) => Math.min(index + 1, STEPS.length - 1));
  };

  const mergeAfterConflict = async () => {
    setSaving(true);
    setError(null);
    try {
      const latest = await getInstallationSetupDraft();
      const merged = structuredClone(latest.payload);
      for (const key of dirtySections) {
        const localSection = payload[key];
        if (localSection === undefined) delete merged[key];
        else Object.assign(merged, { [key]: localSection });
      }
      const saved = await saveInstallationSetupDraft(
        merged,
        latest.lock_version,
      );
      setDraft(saved);
      setPayload(saved.payload);
      setDirtySections(new Set());
      setConflict(null);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Không áp dụng lại được thay đổi.",
      );
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Loading />;
  if (!draft || !catalog) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Không tải được thiết lập</AlertTitle>
        <AlertDescription className="gap-4">
          <p>{error ?? "Máy chủ chưa trả về bản nháp hợp lệ."}</p>
          <Button type="button" variant="outline" onClick={() => void load()}>
            <RefreshCw />
            Thử lại
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="installation-wizard mx-auto grid w-full max-w-6xl gap-6 lg:grid-cols-[16rem_minmax(0,1fr)]">
      <aside className="min-w-0 lg:order-1">
        <SetupStepper
          ariaLabel="Các bước thiết lập"
          items={STEPS.map((step) => ({
            key: step.key,
            label: step.label,
            complete: draft.section_completion[step.key],
          }))}
          currentIndex={currentStep}
          onSelect={navigateToStep}
        />
      </aside>

      <Card className="min-w-0 bg-card lg:order-2">
        <CardHeader className="border-b">
          <CardTitle
            ref={headingRef}
            tabIndex={-1}
            className="text-page-title outline-none"
          >
            {current.title}
          </CardTitle>
          <CardDescription className="text-body">
            {current.description}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-6 pt-6">
          {error ? (
            <Alert variant="destructive">
              <AlertTitle>Không thể tiếp tục</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
          {conflict ? (
            <Alert variant="destructive">
              <AlertTitle>Bản nháp đã được thay đổi ở nơi khác</AlertTitle>
              <AlertDescription className="gap-3">
                <p>Thay đổi chưa lưu của bạn vẫn được giữ trong trang này.</p>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={saving}
                    onClick={() => void load()}
                  >
                    Tải bản mới
                  </Button>
                  <Button
                    type="button"
                    disabled={saving}
                    onClick={() => void mergeAfterConflict()}
                  >
                    Áp dụng lại phần đã sửa
                  </Button>
                </div>
              </AlertDescription>
            </Alert>
          ) : null}

          {current.key === "pack_capabilities" ? (
            <PackCapabilitiesStep
              catalog={catalog}
              issues={currentIssues}
              value={payload.pack_capabilities}
              onChange={(value) => updateSection("pack_capabilities", value)}
            />
          ) : null}
          {current.key === "knowledge_templates" ? (
            <>
              <section className="flex flex-col gap-3 border-b border-border pb-6 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h3 className="text-section-title font-semibold text-foreground">
                    Tài liệu tham khảo (tùy chọn)
                  </h3>
                  <p className="mt-1 text-helper text-muted-foreground">
                    Tải tài liệu để chatbot tham khảo. Bạn có thể thêm hoặc thay
                    đổi sau.
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setKnowledgeUploadOpen(true)}
                >
                  Thêm tài liệu
                </Button>
              </section>
              <KnowledgeUpload
                open={knowledgeUploadOpen}
                onOpenChange={setKnowledgeUploadOpen}
              />
            </>
          ) : null}
          {current.key === "persona" ? (
            <PersonaStep
              catalog={catalog}
              issues={currentIssues}
              value={payload.persona}
              onChange={(value) => updateSection("persona", value)}
              onRegisterSave={registerPersonaSaver}
            />
          ) : null}
          {current.key === "providers_integrations" ? (
            <ProvidersIntegrationsStep
              catalog={catalog}
              issues={currentIssues}
              value={payload.providers_integrations}
              onChange={(value) =>
                updateSection("providers_integrations", value)
              }
              onRegisterSecretSaver={registerProviderSecretSaver}
            />
          ) : null}

          <div className="flex flex-col-reverse gap-3 border-t pt-5 sm:flex-row sm:items-center sm:justify-between">
            <Button
              type="button"
              variant="outline"
              disabled={currentStep === 0 || saving}
              onClick={() => navigateToStep(Math.max(0, currentStep - 1))}
            >
              <ChevronLeft />
              Quay lại
            </Button>
            <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
              {dirtySections.has(section) ? (
                <Button
                  type="button"
                  variant="ghost"
                  disabled={saving}
                  onClick={discardCurrentChanges}
                >
                  Bỏ thay đổi
                </Button>
              ) : null}
              <Button
                type="button"
                disabled={saving}
                onClick={() => void saveAndContinue()}
              >
                Lưu và tiếp tục
                <ChevronRight />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
