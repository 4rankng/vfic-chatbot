import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type {
  IdentityBrandingDraft,
  InstallationCatalog,
  InstallationIssue,
  PackCapabilitiesDraft,
  PersonaDraft,
  ProvidersIntegrationsDraft,
  RegionalTerminologyDraft,
  WorkflowDraft,
} from "../../../installation/installation-client";
import {
  createSetupPersona,
  getSetupPersonaTemplate,
  getZaloSetupStatus,
  getModelIntegrationStatus,
  isSupportedModelIntegration,
  listSetupPersonas,
  listSetupPersonaVersions,
  saveModelIntegrationSecret,
  saveZaloSetupSecrets,
  testZaloSetupChannel,
  type PersonaOption,
  type DisabledSetupFollowupRules,
  type SupportedModelIntegration,
  type ZaloSecretDraft,
} from "../../../installation/setup-authoring-client";
import { describeInstallationIssue } from "../installation-issues";
import { Field } from "../Field";
import { RadioCard } from "../RadioCard";
import { SetupSection } from "../SetupSection";
import { WorkflowAuthoringPage } from "../../../workflows/WorkflowAuthoringPage";
import { listWorkflowVersions } from "../../../workflows/workflow-authoring-client";

type CommonStepProps = {
  catalog: InstallationCatalog;
  issues: InstallationIssue[];
};

const FieldError = ({
  issues,
  path,
}: {
  issues: InstallationIssue[];
  path: string;
}) => {
  const issue = issues.find((item) => item.path?.endsWith(path));
  return issue ? (
    <p className="text-meta font-medium text-destructive" role="alert">
      {describeInstallationIssue(issue)}
    </p>
  ) : null;
};

const StepIssues = ({ issues }: { issues: InstallationIssue[] }) =>
  issues.length > 0 ? (
    <Alert variant="destructive">
      <AlertTitle>Cần kiểm tra lại</AlertTitle>
      <AlertDescription>
        <ul className="list-disc space-y-1 pl-4 text-body">
          {issues.map((issue, index) => (
            <li key={`${issue.code}-${issue.path ?? index}`}>
              {describeInstallationIssue(issue)}
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  ) : null;

const optional = (value: string): string | undefined => {
  const trimmed = value.trim();
  return trimmed || undefined;
};

const disabledSetupFollowupRules = (): DisabledSetupFollowupRules => ({
  hot: { enabled: false, cadence_hours: [], eligible_stages: [] },
  warm: { enabled: false, cadence_hours: [], eligible_stages: [] },
  not_interested: { enabled: false, cadence_hours: [], eligible_stages: [] },
});

export const IdentityBrandingStep = ({
  value,
  onChange,
  issues,
}: CommonStepProps & {
  value?: IdentityBrandingDraft;
  onChange: (value: IdentityBrandingDraft) => void;
}) => {
  const identity = value?.customer_identity;
  const branding = value?.branding;
  const updateIdentity = (
    field: keyof IdentityBrandingDraft["customer_identity"],
    next: string,
  ) =>
    onChange({
      customer_identity: {
        display_name: identity?.display_name ?? "",
        ...identity,
        [field]: field === "display_name" ? next : optional(next),
      },
      branding: branding ?? { app_name: "" },
    });
  const updateBranding = (
    field: keyof IdentityBrandingDraft["branding"],
    next: string,
  ) =>
    onChange({
      customer_identity: identity ?? { display_name: "" },
      branding: {
        app_name: branding?.app_name ?? "",
        ...branding,
        [field]: field === "app_name" ? next : optional(next),
      },
    });

  return (
    <fieldset className="grid gap-6" aria-describedby="identity-help">
      <legend className="sr-only">Danh tính và thương hiệu</legend>
      <p id="identity-help" className="text-body text-muted-foreground">
        Nhập thông tin của khách hàng này. Hệ thống không tự điền tên, logo hoặc
        nội dung ngành.
      </p>
      <StepIssues issues={issues} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Tên hiển thị" required colSpan="sm:col-span-2">
          {({ id }) => (
            <>
              <Input
                id={id}
                value={identity?.display_name ?? ""}
                onChange={(event) =>
                  updateIdentity("display_name", event.target.value)
                }
                required
                maxLength={160}
                autoFocus
              />
              <FieldError issues={issues} path="display_name" />
            </>
          )}
        </Field>
        <Field label="Tên pháp lý">
          {({ id }) => (
            <Input
              id={id}
              value={identity?.legal_name ?? ""}
              onChange={(event) =>
                updateIdentity("legal_name", event.target.value)
              }
              maxLength={240}
            />
          )}
        </Field>
        <Field label="Tên ứng dụng" required>
          {({ id }) => (
            <Input
              id={id}
              value={branding?.app_name ?? ""}
              onChange={(event) =>
                updateBranding("app_name", event.target.value)
              }
              maxLength={160}
              required
            />
          )}
        </Field>
        <Field label="Tên bộ phận hỗ trợ">
          {({ id }) => (
            <Input
              id={id}
              value={identity?.support_name ?? ""}
              onChange={(event) =>
                updateIdentity("support_name", event.target.value)
              }
              maxLength={160}
            />
          )}
        </Field>
        <Field label="Email hỗ trợ">
          {({ id }) => (
            <Input
              id={id}
              type="email"
              value={identity?.support_email ?? ""}
              onChange={(event) =>
                updateIdentity("support_email", event.target.value)
              }
              maxLength={254}
            />
          )}
        </Field>
        <Field label="Số điện thoại hỗ trợ">
          {({ id }) => (
            <Input
              id={id}
              value={identity?.support_phone ?? ""}
              onChange={(event) =>
                updateIdentity("support_phone", event.target.value)
              }
              maxLength={32}
            />
          )}
        </Field>
        <Field label="Website">
          {({ id }) => (
            <Input
              id={id}
              type="url"
              value={identity?.website_url ?? ""}
              onChange={(event) =>
                updateIdentity("website_url", event.target.value)
              }
              maxLength={500}
            />
          )}
        </Field>
        <Field label="Địa chỉ" colSpan="sm:col-span-2">
          {({ id }) => (
            <Input
              id={id}
              value={identity?.address ?? ""}
              onChange={(event) =>
                updateIdentity("address", event.target.value)
              }
              maxLength={500}
            />
          )}
        </Field>
        <Field label="Màu chính">
          {({ id }) => (
            <Input
              id={id}
              value={branding?.primary_color ?? ""}
              onChange={(event) =>
                updateBranding("primary_color", event.target.value)
              }
              pattern="#[0-9a-fA-F]{6}"
              placeholder="#000000"
            />
          )}
        </Field>
        <Field label="Màu phụ">
          {({ id }) => (
            <Input
              id={id}
              value={branding?.secondary_color ?? ""}
              onChange={(event) =>
                updateBranding("secondary_color", event.target.value)
              }
              pattern="#[0-9a-fA-F]{6}"
              placeholder="#000000"
            />
          )}
        </Field>
      </div>
    </fieldset>
  );
};

export const RegionalTerminologyStep = ({
  value,
  onChange,
  catalog,
  selectedPackKey,
  issues,
}: CommonStepProps & {
  value?: RegionalTerminologyDraft;
  selectedPackKey?: string;
  onChange: (value: RegionalTerminologyDraft) => void;
}) => {
  const terminologyKeys = useMemo(
    () =>
      catalog.packs.find((pack) => pack.key === selectedPackKey)
        ?.terminology_keys ?? [],
    [catalog.packs, selectedPackKey],
  );
  const current = value ?? {
    locale: "",
    timezone: "",
    currency: "",
    terminology: {},
  };
  return (
    <fieldset className="grid gap-6">
      <legend className="sr-only">Khu vực và thuật ngữ</legend>
      <p className="text-body text-muted-foreground">
        Chỉ các giá trị được máy chủ hỗ trợ mới có thể lưu. Không có khu vực
        hoặc tiền tệ mặc định.
      </p>
      <StepIssues issues={issues} />
      {!selectedPackKey ? (
        <Alert variant="info">
          <AlertTitle>Chưa chọn gói ngành</AlertTitle>
          <AlertDescription>
            Hãy chọn gói ngành ở bước trước để tải đúng bộ thuật ngữ.
          </AlertDescription>
        </Alert>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Ngôn ngữ" required>
          {({ id }) => (
            <select
              id={id}
              className="border-input bg-background flex h-10 w-full rounded-md border px-3 text-control text-foreground shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50"
              value={current.locale}
              onChange={(event) =>
                onChange({ ...current, locale: event.target.value })
              }
              required
              autoFocus
            >
              <option value="">Chọn ngôn ngữ</option>
              {catalog.locales.map((locale) => (
                <option key={locale} value={locale}>
                  {locale}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Tiền tệ" required>
          {({ id }) => (
            <select
              id={id}
              className="border-input bg-background flex h-10 w-full rounded-md border px-3 text-control text-foreground shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50"
              value={current.currency}
              onChange={(event) =>
                onChange({ ...current, currency: event.target.value })
              }
              required
            >
              <option value="">Chọn tiền tệ</option>
              {catalog.currencies.map((currency) => (
                <option key={currency} value={currency}>
                  {currency}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Múi giờ IANA" required colSpan="sm:col-span-2">
          {({ id }) => (
            <Input
              id={id}
              value={current.timezone}
              onChange={(event) =>
                onChange({ ...current, timezone: event.target.value })
              }
              placeholder="Continent/City"
              required
              maxLength={64}
            />
          )}
        </Field>
        {terminologyKeys.map((key) => (
          <Field key={key} label={`Thuật ngữ: ${key}`}>
            {({ id }) => (
              <Input
                id={id}
                value={current.terminology[key] ?? ""}
                onChange={(event) =>
                  onChange({
                    ...current,
                    terminology: {
                      ...current.terminology,
                      [key]: event.target.value,
                    },
                  })
                }
                maxLength={80}
              />
            )}
          </Field>
        ))}
      </div>
    </fieldset>
  );
};

export const PackCapabilitiesStep = ({
  value,
  onChange,
  catalog,
  issues,
}: CommonStepProps & {
  value?: PackCapabilitiesDraft;
  onChange: (value: PackCapabilitiesDraft) => void;
}) => {
  const selectedPack = catalog.packs.find(
    (pack) => pack.key === value?.pack_key,
  );
  const packCopy: Record<string, { title: string; description: string }> = {
    recruitment: {
      title: "Tuyển dụng",
      description:
        "Ứng viên, vị trí tuyển, tư vấn việc làm và quy trình tuyển dụng.",
    },
    shopping: {
      title: "Bán hàng và mua sắm",
      description: "Sản phẩm, đơn hàng và quy trình hỗ trợ mua sắm.",
    },
    product_advisory: {
      title: "Tư vấn sản phẩm",
      description: "Tra cứu và tư vấn dựa trên tài liệu sản phẩm.",
    },
  };
  return (
    <fieldset className="grid gap-6">
      <legend className="sr-only">Gói ngành và chức năng</legend>
      <StepIssues issues={issues} />
      <div className="grid gap-3 sm:grid-cols-2">
        {catalog.packs.map((pack) => (
          <RadioCard
            key={pack.key}
            name="setup-pack"
            value={pack.key}
            checked={value?.pack_key === pack.key}
            onChange={() =>
              onChange({
                pack_key: pack.key,
                capability_ids: pack.capability_ids,
              })
            }
            title={packCopy[pack.key]?.title ?? pack.key}
            description={
              packCopy[pack.key]?.description ?? `Phiên bản ${pack.version}`
            }
          />
        ))}
      </div>
      {selectedPack ? (
        <p className="text-meta text-muted-foreground">
          Hệ thống sẽ dùng toàn bộ chức năng đã kiểm duyệt của loại hình này:{" "}
          {selectedPack.capability_ids.join(", ")}.
        </p>
      ) : null}
    </fieldset>
  );
};

export const WorkflowStep = ({
  value,
  onChange,
  catalog,
  selectedPackKey,
  syncToken,
  issues,
}: CommonStepProps & {
  value?: WorkflowDraft;
  selectedPackKey?: string;
  syncToken?: number;
  onChange: (value: WorkflowDraft | undefined) => void;
}) => {
  const initial = value?.workflow_policy;
  const [workflowId, setWorkflowId] = useState(initial?.workflow_id ?? "");
  const [workflowVersionId, setWorkflowVersionId] = useState(
    initial?.workflow_version_id ?? "",
  );
  const [authoredVersions, setAuthoredVersions] = useState(
    catalog.authored_workflow_versions,
  );
  const [versionError, setVersionError] = useState<string | null>(null);
  const [handoffMode, setHandoffMode] = useState<
    "" | WorkflowDraft["workflow_policy"]["handoff_mode"]
  >(initial?.handoff_mode ?? "");
  const [automationChoice, setAutomationChoice] = useState<
    "" | "enabled" | "disabled"
  >(initial ? (initial.automation_enabled ? "enabled" : "disabled") : "");
  const allowedIds = useMemo(
    () =>
      catalog.packs.find((pack) => pack.key === selectedPackKey)
        ?.workflow_ids ?? [],
    [catalog.packs, selectedPackKey],
  );
  const workflows = useMemo(
    () =>
      catalog.workflows.filter((workflow) => allowedIds.includes(workflow.id)),
    [allowedIds, catalog.workflows],
  );
  const selectedWorkflow = workflows.find(
    (workflow) => workflow.id === workflowId,
  );
  useEffect(() => {
    const policy = value?.workflow_policy;
    const version = catalog.authored_workflow_versions.find(
      (candidate) =>
        candidate.id === policy?.workflow_version_id &&
        candidate.checksum === policy.workflow_version_checksum &&
        candidate.pack_key === selectedPackKey &&
        candidate.workflow_key === policy?.workflow_id,
    );
    if (!policy || !version || !allowedIds.includes(policy.workflow_id)) {
      setWorkflowId("");
      setWorkflowVersionId("");
      setHandoffMode("");
      setAutomationChoice("");
      return;
    }
    setWorkflowId(policy.workflow_id);
    setWorkflowVersionId(policy.workflow_version_id);
    setHandoffMode(policy.handoff_mode);
    setAutomationChoice(policy.automation_enabled ? "enabled" : "disabled");
  }, [
    allowedIds,
    catalog.authored_workflow_versions,
    selectedPackKey,
    syncToken,
    value,
  ]);
  const selectableVersions = authoredVersions
    .filter(
      (version) =>
        version.pack_key === selectedPackKey &&
        version.workflow_key === workflowId,
    )
    .sort((left, right) => right.version_no - left.version_no);
  const reloadVersions = async () => {
    setVersionError(null);
    try {
      const versions = await listWorkflowVersions();
      setAuthoredVersions(versions);
    } catch (cause) {
      setVersionError(
        cause instanceof Error
          ? cause.message
          : "Không tải lại được phiên bản quy trình.",
      );
    }
  };
  const commit = (
    nextWorkflowId: string,
    nextWorkflowVersionId: string,
    nextHandoffMode: "" | WorkflowDraft["workflow_policy"]["handoff_mode"],
    nextAutomationChoice: "" | "enabled" | "disabled",
  ) => {
    const version = authoredVersions.find(
      (candidate) =>
        candidate.id === nextWorkflowVersionId &&
        candidate.pack_key === selectedPackKey &&
        candidate.workflow_key === nextWorkflowId,
    );
    if (
      !nextWorkflowId ||
      !version ||
      !nextHandoffMode ||
      !nextAutomationChoice
    ) {
      onChange(undefined);
      return;
    }
    onChange({
      workflow_policy: {
        workflow_id: nextWorkflowId,
        workflow_version_id: version.id,
        workflow_version_checksum: version.checksum,
        handoff_mode: nextHandoffMode,
        automation_enabled: nextAutomationChoice === "enabled",
      },
    });
  };
  return (
    <fieldset className="grid gap-6">
      <legend className="sr-only">Quy trình và bàn giao</legend>
      <StepIssues issues={issues} />
      {!selectedPackKey ? (
        <Alert variant="info">
          <AlertTitle>Chưa chọn gói</AlertTitle>
          <AlertDescription>
            Hãy chọn gói ở bước trước để tải đúng quy trình.
          </AlertDescription>
        </Alert>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Quy trình" required colSpan="sm:col-span-2">
          {({ id }) => (
            <select
              id={id}
              className="border-input bg-background flex h-10 w-full rounded-md border px-3 text-control text-foreground shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50"
              value={workflowId}
              onChange={(event) => {
                const next = event.target.value;
                setWorkflowId(next);
                setWorkflowVersionId("");
                setHandoffMode("");
                commit(next, "", "", automationChoice);
              }}
              required
              autoFocus
            >
              <option value="">Chọn quy trình</option>
              {workflows.map((workflow) => (
                <option key={workflow.id} value={workflow.id}>
                  {workflow.id}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field
          label="Phiên bản đã xuất bản"
          required
          colSpan="sm:col-span-2"
          helper={
            workflowId && selectableVersions.length === 0
              ? "Chưa có phiên bản nào. Hãy tạo và xuất bản một phiên bản bên dưới."
              : undefined
          }
        >
          {({ id }) => (
            <>
              <select
                id={id}
                className="border-input bg-background flex h-10 w-full rounded-md border px-3 text-control text-foreground shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
                value={workflowVersionId}
                disabled={!workflowId}
                onChange={(event) => {
                  const next = event.target.value;
                  setWorkflowVersionId(next);
                  commit(workflowId, next, handoffMode, automationChoice);
                }}
                required
              >
                <option value="">Chọn phiên bản</option>
                {selectableVersions.map((version) => (
                  <option key={version.id} value={version.id}>
                    {version.label} — phiên bản {version.version_no}
                  </option>
                ))}
              </select>
              {versionError ? (
                <p className="text-meta text-destructive" role="alert">
                  {versionError}
                </p>
              ) : null}
            </>
          )}
        </Field>
        <Field label="Cách bàn giao" required>
          {({ id }) => (
            <select
              id={id}
              className="border-input bg-background flex h-10 w-full rounded-md border px-3 text-control text-foreground shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50"
              value={handoffMode}
              onChange={(event) => {
                const next = event.target.value as
                  "" | WorkflowDraft["workflow_policy"]["handoff_mode"];
                setHandoffMode(next);
                commit(workflowId, workflowVersionId, next, automationChoice);
              }}
              required
            >
              <option value="">Chọn cách bàn giao</option>
              {(selectedWorkflow?.handoff_modes ?? []).map((mode) => (
                <option key={mode} value={mode}>
                  {mode === "manual"
                    ? "Thủ công"
                    : mode === "assisted"
                      ? "Có hỗ trợ"
                      : "Tự động"}
                </option>
              ))}
            </select>
          )}
        </Field>
        <fieldset className="grid gap-2 sm:col-span-2">
          <legend className="text-control font-medium text-foreground">
            Tự động hóa *
          </legend>
          <div className="grid gap-3 sm:grid-cols-2">
            <RadioCard
              name="setup-automation"
              value="enabled"
              checked={automationChoice === "enabled"}
              onChange={() => {
                setAutomationChoice("enabled");
                commit(workflowId, workflowVersionId, handoffMode, "enabled");
              }}
              title="Bật tự động hóa"
            />
            <RadioCard
              name="setup-automation"
              value="disabled"
              checked={automationChoice === "disabled"}
              onChange={() => {
                setAutomationChoice("disabled");
                commit(workflowId, workflowVersionId, handoffMode, "disabled");
              }}
              title="Không bật tự động hóa"
            />
          </div>
        </fieldset>
      </div>
      {selectedPackKey && workflowId ? (
        <div className="border-t pt-5">
          <WorkflowAuthoringPage
            key={`${selectedPackKey}:${workflowId}`}
            packKey={selectedPackKey}
            workflowKey={workflowId}
            embedded
            onPublished={reloadVersions}
          />
        </div>
      ) : null}
    </fieldset>
  );
};

export const PersonaStep = ({
  onChange,
  issues,
  onRegisterSave,
}: CommonStepProps & {
  value?: PersonaDraft;
  onChange: (value: PersonaDraft) => void;
  onRegisterSave?: (save: (() => Promise<PersonaDraft | null>) | null) => void;
}) => {
  const [personas, setPersonas] = useState<PersonaOption[]>([]);
  const [selectedPersonaId, setSelectedPersonaId] = useState("");
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [templateBusy, setTemplateBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    try {
      setPersonas(await listSetupPersonas());
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Không tải được Agent.",
      );
    }
  }, []);
  useEffect(() => {
    void reload();
  }, [reload]);
  const selectPersona = useCallback(
    async (personaId: string) => {
      if (!personaId) {
        setSelectedPersonaId("");
        return;
      }
      try {
        const latest = [...(await listSetupPersonaVersions(personaId))].sort(
          (left, right) => right.version_no - left.version_no,
        )[0];
        if (!latest) {
          setError(
            "Agent này chưa sẵn sàng để sử dụng. Hãy chọn Agent khác hoặc tạo Agent mới.",
          );
          return;
        }
        setError(null);
        setSelectedPersonaId(personaId);
        onChange({ persona_version_id: latest.id, checksum: latest.checksum });
      } catch {
        setError("Không tải được Agent. Vui lòng thử lại.");
      }
    },
    [onChange],
  );
  const create = useCallback(async (): Promise<PersonaDraft | null> => {
    if (!name.trim() && !body.trim()) return null;
    if (!name.trim() || !body.trim()) {
      setError("Tên và nội dung Agent là bắt buộc.");
      return null;
    }
    setError(null);
    try {
      const persona = await createSetupPersona({
        name: name.trim(),
        body_md: body.trim(),
        notes: null,
        followup_rules: disabledSetupFollowupRules(),
      });
      const nextVersions = await listSetupPersonaVersions(persona.id);
      const latest = nextVersions.sort(
        (a, b) => b.version_no - a.version_no,
      )[0];
      if (!latest)
        throw new Error("Không thể tạo Agent mới, vui lòng thử lại.");
      const created = {
        persona_version_id: latest.id,
        checksum: latest.checksum,
      };
      onChange(created);
      setName("");
      setBody("");
      await reload();
      await selectPersona(persona.id);
      return created;
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Không tạo được Agent.",
      );
      return null;
    }
  }, [body, name, onChange, reload, selectPersona]);
  useEffect(() => {
    onRegisterSave?.(create);
    return () => onRegisterSave?.(null);
  }, [create, onRegisterSave]);
  const loadTemplate = async () => {
    setTemplateBusy(true);
    setError(null);
    try {
      setBody(await getSetupPersonaTemplate());
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Không tải được mẫu Agent.",
      );
    } finally {
      setTemplateBusy(false);
    }
  };
  return (
    <div className="grid gap-6">
      <StepIssues issues={issues} />
      <SetupSection title="Chọn Agent">
        <Field label="Agent">
          {({ id }) => (
            <select
              id={id}
              className="border-input bg-background flex h-10 w-full rounded-md border px-3 text-control text-foreground shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50"
              value={selectedPersonaId}
              onChange={(event) => void selectPersona(event.target.value)}
              aria-label="Agent"
            >
              <option value="">Chọn Agent</option>
              {personas.map((persona) => (
                <option key={persona.id} value={persona.id}>
                  {persona.name}
                </option>
              ))}
            </select>
          )}
        </Field>
      </SetupSection>
      <SetupSection
        title="Tạo Agent mới"
        description="Dùng mẫu bắt đầu rồi chỉnh sửa để phù hợp với khách hàng này."
        trailing={
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={templateBusy}
            onClick={() => void loadTemplate()}
          >
            {templateBusy ? <Loader2 className="animate-spin" /> : null}
            Tải mẫu
          </Button>
        }
      >
        <Field label="Tên Agent" required>
          {({ id }) => (
            <Input
              id={id}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          )}
        </Field>
        <Field label="Nội dung và chính sách" required>
          {({ id }) => (
            <Textarea
              id={id}
              value={body}
              onChange={(event) => setBody(event.target.value)}
              rows={10}
            />
          )}
        </Field>
        {error ? (
          <p className="text-meta text-destructive" role="alert">
            {error}
          </p>
        ) : null}
      </SetupSection>
    </div>
  );
};

const PROVIDER_LABELS: Record<SupportedModelIntegration, string> = {
  minimax: "MiniMax",
  openrouter: "OpenRouter",
};

type ProviderSecretPanelProps = {
  integrationKey: SupportedModelIntegration;
  onRegisterSave: (
    key: SupportedModelIntegration,
    save: (() => Promise<boolean>) | null,
  ) => void;
};

const ProviderSecretPanel = ({
  integrationKey,
  onRegisterSave,
}: ProviderSecretPanelProps) => {
  const [configured, setConfigured] = useState(false);
  const [secret, setSecret] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void getModelIntegrationStatus(integrationKey)
      .then((status) => {
        if (!active) return;
        setConfigured(
          "minimax_api_key" in status
            ? status.minimax_api_key.configured
            : status.openrouter_api_key.configured,
        );
      })
      .catch(() => {
        if (active) setMessage("Không tải được trạng thái tích hợp.");
      });
    return () => {
      active = false;
    };
  }, [integrationKey]);
  const save = useCallback(async (): Promise<boolean> => {
    if (!secret.trim()) return true;
    setMessage(null);
    try {
      await saveModelIntegrationSecret(integrationKey, secret.trim());
      setSecret("");
      setConfigured(true);
      setMessage("Đã lưu bí mật ở dạng mã hóa.");
      return true;
    } catch (cause) {
      setMessage(
        cause instanceof Error ? cause.message : "Không lưu được bí mật.",
      );
      return false;
    }
  }, [integrationKey, secret]);
  useEffect(() => {
    onRegisterSave(integrationKey, save);
    return () => onRegisterSave(integrationKey, null);
  }, [integrationKey, onRegisterSave, save]);
  return (
    <div className="grid content-start gap-4">
      <Field
        label={`${PROVIDER_LABELS[integrationKey]} API Key`}
        helper={configured ? "Đã có khóa được mã hóa" : "Chưa có khóa"}
      >
        {({ id, describedBy }) => (
          <Input
            id={id}
            type="password"
            autoComplete="off"
            aria-describedby={describedBy}
            value={secret}
            onChange={(event) => setSecret(event.target.value)}
          />
        )}
      </Field>
      {message ? (
        <p className="text-meta text-muted-foreground" aria-live="polite">
          {message}
        </p>
      ) : null}
    </div>
  );
};

const EMPTY_ZALO_SECRETS: ZaloSecretDraft = {
  zalo_bot_token: "",
  zalo_bot_webhook_secret: "",
  zalo_oa_app_id: "",
  zalo_oa_secret_key: "",
  zalo_oa_access_token: "",
  zalo_oa_refresh_token: "",
};

const ZaloSecretPanel = () => {
  const [status, setStatus] = useState<Awaited<
    ReturnType<typeof getZaloSetupStatus>
  > | null>(null);
  const [form, setForm] = useState<ZaloSecretDraft>(EMPTY_ZALO_SECRETS);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void getZaloSetupStatus()
      .then((next) => {
        if (active) setStatus(next);
      })
      .catch(() => {
        if (active) setMessage("Không tải được trạng thái Zalo.");
      });
    return () => {
      active = false;
    };
  }, []);
  const setField = (field: keyof ZaloSecretDraft, next: string) =>
    setForm((current) => ({ ...current, [field]: next }));
  const save = async () => {
    const payload = Object.fromEntries(
      Object.entries(form).filter(([, value]) => value.trim()),
    ) as Partial<ZaloSecretDraft>;
    if (Object.keys(payload).length === 0) return;
    setBusy(true);
    setMessage(null);
    try {
      setStatus(await saveZaloSetupSecrets(payload));
      setForm(EMPTY_ZALO_SECRETS);
      setMessage("Đã lưu thông tin Zalo ở kho mã hóa.");
    } catch (cause) {
      setMessage(
        cause instanceof Error ? cause.message : "Không lưu được Zalo.",
      );
    } finally {
      setBusy(false);
    }
  };
  const test = async (channel: "bot" | "oa") => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await testZaloSetupChannel(channel);
      setMessage(
        result.connected
          ? `Kênh ${channel.toUpperCase()} đã kết nối.`
          : result.missing.length > 0
            ? `Thiếu: ${result.missing.join(", ")}`
            : result.errors.join("; ") || "Kênh chưa kết nối.",
      );
    } catch (cause) {
      setMessage(
        cause instanceof Error ? cause.message : "Không kiểm tra được Zalo.",
      );
    } finally {
      setBusy(false);
    }
  };
  const fields: Array<{
    key: keyof ZaloSecretDraft;
    label: string;
    secret: boolean;
  }> = [
    { key: "zalo_bot_token", label: "Bot token", secret: true },
    {
      key: "zalo_bot_webhook_secret",
      label: "Bot webhook secret",
      secret: true,
    },
    { key: "zalo_oa_app_id", label: "OA App ID", secret: false },
    { key: "zalo_oa_secret_key", label: "OA secret key", secret: true },
    { key: "zalo_oa_access_token", label: "OA access token", secret: true },
    { key: "zalo_oa_refresh_token", label: "OA refresh token", secret: true },
  ];
  const configuredCount = status
    ? [
        status.zalo_bot_token,
        status.zalo_bot_webhook_secret,
        status.zalo_oa_app_id,
        status.zalo_oa_secret_key,
        status.zalo_oa_access_token,
        status.zalo_oa_refresh_token,
      ].filter((item) => item.configured).length
    : 0;
  return (
    <SetupSection
      title="Zalo"
      description={`${configuredCount}/6 trường đã cấu hình. Giá trị bí mật đã lưu không được tải lại vào biểu mẫu.`}
      className="sm:col-span-2"
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {fields.map((field) => (
          <Field key={field.key} label={field.label}>
            {({ id }) => (
              <Input
                id={id}
                type={field.secret ? "password" : "text"}
                autoComplete="off"
                value={form[field.key]}
                onChange={(event) => setField(field.key, event.target.value)}
              />
            )}
          </Field>
        ))}
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        <Button
          type="button"
          disabled={busy || !Object.values(form).some((item) => item.trim())}
          onClick={() => void save()}
        >
          Lưu thông tin Zalo
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          onClick={() => void test("bot")}
        >
          Kiểm tra Bot
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          onClick={() => void test("oa")}
        >
          Kiểm tra OA
        </Button>
      </div>
      {message ? (
        <p className="text-meta text-muted-foreground" aria-live="polite">
          {message}
        </p>
      ) : null}
    </SetupSection>
  );
};

const selectClassName =
  "border-input bg-background flex h-10 w-full rounded-md border px-3 text-control text-foreground shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50";

export const ProvidersIntegrationsStep = ({
  value,
  onChange,
  catalog,
  issues,
  onRegisterSecretSaver,
}: CommonStepProps & {
  value?: ProvidersIntegrationsDraft;
  onChange: (value: ProvidersIntegrationsDraft) => void;
  onRegisterSecretSaver?: (save: (() => Promise<boolean>) | null) => void;
}) => {
  const [policy, setPolicy] = useState(() => ({
    chatIntegrationKey: value?.provider_policy.chat_integration_key ?? "",
    chatModel: value?.provider_policy.chat_model ?? "",
    embeddingIntegrationKey:
      value?.provider_policy.embedding_integration_key ?? "",
    embeddingModel: value?.provider_policy.embedding_model ?? "",
    temperature: value ? String(value.provider_policy.temperature) : "",
    maxOutputTokens: value
      ? String(value.provider_policy.max_output_tokens)
      : "",
  }));
  const selectedKeys = Array.from(
    new Set(
      [policy.chatIntegrationKey, policy.embeddingIntegrationKey].filter(
        Boolean,
      ),
    ),
  );
  const secretSavers = useRef(
    new Map<SupportedModelIntegration, () => Promise<boolean>>(),
  );
  const registerSecretSaver = useCallback(
    (key: SupportedModelIntegration, save: (() => Promise<boolean>) | null) => {
      if (save) secretSavers.current.set(key, save);
      else secretSavers.current.delete(key);
    },
    [],
  );
  const savePendingSecrets = useCallback(async (): Promise<boolean> => {
    const results = await Promise.all(
      Array.from(secretSavers.current.values(), (save) => save()),
    );
    return results.every(Boolean);
  }, []);
  useEffect(() => {
    onRegisterSecretSaver?.(savePendingSecrets);
    return () => onRegisterSecretSaver?.(null);
  }, [onRegisterSecretSaver, savePendingSecrets]);
  const commit = (nextPolicy: typeof policy) => {
    const temperature = Number(nextPolicy.temperature);
    const maxOutputTokens = Number(nextPolicy.maxOutputTokens);
    if (
      !nextPolicy.chatIntegrationKey ||
      !nextPolicy.chatModel.trim() ||
      !nextPolicy.embeddingIntegrationKey ||
      !nextPolicy.embeddingModel.trim() ||
      nextPolicy.temperature === "" ||
      !Number.isFinite(temperature) ||
      nextPolicy.maxOutputTokens === "" ||
      !Number.isInteger(maxOutputTokens)
    ) {
      return;
    }
    onChange({
      provider_policy: {
        chat_integration_key: nextPolicy.chatIntegrationKey,
        chat_model: nextPolicy.chatModel.trim(),
        embedding_integration_key: nextPolicy.embeddingIntegrationKey,
        embedding_model: nextPolicy.embeddingModel.trim(),
        temperature,
        max_output_tokens: maxOutputTokens,
      },
      integration_requirements: [],
      authentication_policy: { email_password_enabled: true },
    });
  };
  const updatePolicy = (patch: Partial<typeof policy>) => {
    const next = { ...policy, ...patch };
    setPolicy(next);
    commit(next);
  };
  return (
    <fieldset className="grid gap-6">
      <legend className="sr-only">Nhà cung cấp và tích hợp</legend>
      <StepIssues issues={issues} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Nhà cung cấp chat" required>
          {({ id }) => (
            <select
              id={id}
              className={selectClassName}
              value={policy.chatIntegrationKey}
              onChange={(event) =>
                updatePolicy({ chatIntegrationKey: event.target.value })
              }
            >
              <option value="">Chọn nhà cung cấp</option>
              {catalog.integration_keys
                .filter((key) => key === "minimax" || key === "openrouter")
                .map((key) => (
                  <option key={key} value={key}>
                    {key}
                  </option>
                ))}
            </select>
          )}
        </Field>
        <Field label="Model chat" required>
          {({ id }) => (
            <Input
              id={id}
              value={policy.chatModel}
              onChange={(event) =>
                updatePolicy({ chatModel: event.target.value })
              }
            />
          )}
        </Field>
        <Field label="Nhà cung cấp embedding" required>
          {({ id }) => (
            <select
              id={id}
              className={selectClassName}
              value={policy.embeddingIntegrationKey}
              onChange={(event) =>
                updatePolicy({ embeddingIntegrationKey: event.target.value })
              }
            >
              <option value="">Chọn nhà cung cấp</option>
              {catalog.integration_keys
                .filter((key) => key === "openrouter")
                .map((key) => (
                  <option key={key} value={key}>
                    {key}
                  </option>
                ))}
            </select>
          )}
        </Field>
        <Field label="Model embedding" required>
          {({ id }) => (
            <Input
              id={id}
              value={policy.embeddingModel}
              onChange={(event) =>
                updatePolicy({ embeddingModel: event.target.value })
              }
            />
          )}
        </Field>
        <Field label="Temperature" required helper="Giá trị từ 0 đến 2.">
          {({ id }) => (
            <Input
              id={id}
              type="number"
              min={0}
              max={2}
              step="0.1"
              value={policy.temperature}
              onChange={(event) =>
                updatePolicy({ temperature: event.target.value })
              }
            />
          )}
        </Field>
        <Field
          label="Số token đầu ra tối đa"
          required
          helper="Tối đa 131072 token."
        >
          {({ id }) => (
            <Input
              id={id}
              type="number"
              min={1}
              max={131072}
              value={policy.maxOutputTokens}
              onChange={(event) =>
                updatePolicy({ maxOutputTokens: event.target.value })
              }
            />
          )}
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {selectedKeys.filter(isSupportedModelIntegration).map((key) => (
          <ProviderSecretPanel
            key={key}
            integrationKey={key}
            onRegisterSave={registerSecretSaver}
          />
        ))}
        {selectedKeys.includes("zalo") ? <ZaloSecretPanel /> : null}
      </div>
    </fieldset>
  );
};
