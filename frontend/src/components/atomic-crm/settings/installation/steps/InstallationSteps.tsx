import { Check, Loader2, Plus, RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type {
  IdentityBrandingDraft,
  InstallationCatalog,
  InstallationIssue,
  KnowledgeTemplatesDraft,
  PackCapabilitiesDraft,
  PersonaDraft,
  ProvidersIntegrationsDraft,
  RegionalTerminologyDraft,
  WorkflowDraft,
} from "../../../installation/installation-client";
import {
  createSetupPersona,
  createSetupTemplate,
  getZaloSetupStatus,
  getModelIntegrationStatus,
  isSupportedModelIntegration,
  listSetupPersonas,
  listSetupPersonaVersions,
  listSetupTemplates,
  listSetupTemplateVersions,
  previewNewSetupTemplate,
  previewSetupTemplateVersion,
  publishSetupTemplateVersion,
  saveModelIntegrationSecret,
  saveZaloSetupSecrets,
  testModelIntegration,
  testZaloSetupChannel,
  type PersonaOption,
  type PersonaVersionOption,
  type DisabledSetupFollowupRules,
  type SetupTemplate,
  type SetupTemplateVersion,
  type SupportedModelIntegration,
  type ZaloSecretDraft,
} from "../../../installation/setup-authoring-client";
import { describeInstallationIssue } from "../installation-issues";
import { WorkflowAuthoringPage } from "../../../workflows/WorkflowAuthoringPage";
import { listWorkflowVersions } from "../../../workflows/workflow-authoring-client";

type CommonStepProps = {
  catalog: InstallationCatalog;
  issues: InstallationIssue[];
};

const FieldError = ({ issues, path }: { issues: InstallationIssue[]; path: string }) => {
  const issue = issues.find((item) => item.path?.endsWith(path));
  return issue ? (
    <p className="text-xs font-medium text-destructive" role="alert">
      {describeInstallationIssue(issue)}
    </p>
  ) : null;
};

const StepIssues = ({ issues }: { issues: InstallationIssue[] }) =>
  issues.length > 0 ? (
    <Alert variant="destructive">
      <AlertTitle>Cần kiểm tra lại</AlertTitle>
      <AlertDescription>
        <ul className="list-disc space-y-1 pl-4">
          {issues.map((issue, index) => (
            <li key={`${issue.code}-${issue.path ?? index}`}>
              {describeInstallationIssue(issue)}
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  ) : null;

const inputClassName = "min-h-11";
const selectClassName =
  "min-h-11 w-full rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

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
  const updateIdentity = (field: keyof IdentityBrandingDraft["customer_identity"], next: string) =>
    onChange({
      customer_identity: {
        display_name: identity?.display_name ?? "",
        ...identity,
        [field]: field === "display_name" ? next : optional(next),
      },
      branding: branding ?? { app_name: "" },
    });
  const updateBranding = (field: keyof IdentityBrandingDraft["branding"], next: string) =>
    onChange({
      customer_identity: identity ?? { display_name: "" },
      branding: {
        app_name: branding?.app_name ?? "",
        ...branding,
        [field]: field === "app_name" ? next : optional(next),
      },
    });

  return (
    <fieldset className="grid gap-5" aria-describedby="identity-help">
      <legend className="sr-only">Danh tính và thương hiệu</legend>
      <p id="identity-help" className="text-sm leading-6 text-muted-foreground">
        Nhập thông tin của khách hàng này. Hệ thống không tự điền tên, logo hoặc nội dung ngành.
      </p>
      <StepIssues issues={issues} />
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2 sm:col-span-2">
          <Label htmlFor="setup-display-name">Tên hiển thị *</Label>
          <Input
            id="setup-display-name"
            className={inputClassName}
            value={identity?.display_name ?? ""}
            onChange={(event) => updateIdentity("display_name", event.target.value)}
            required
            maxLength={160}
            autoFocus
          />
          <FieldError issues={issues} path="display_name" />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="setup-legal-name">Tên pháp lý</Label>
          <Input id="setup-legal-name" className={inputClassName} value={identity?.legal_name ?? ""} onChange={(event) => updateIdentity("legal_name", event.target.value)} maxLength={240} />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="setup-app-name">Tên ứng dụng *</Label>
          <Input id="setup-app-name" className={inputClassName} value={branding?.app_name ?? ""} onChange={(event) => updateBranding("app_name", event.target.value)} maxLength={160} required />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="setup-support-name">Tên bộ phận hỗ trợ</Label>
          <Input id="setup-support-name" className={inputClassName} value={identity?.support_name ?? ""} onChange={(event) => updateIdentity("support_name", event.target.value)} maxLength={160} />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="setup-support-email">Email hỗ trợ</Label>
          <Input id="setup-support-email" type="email" className={inputClassName} value={identity?.support_email ?? ""} onChange={(event) => updateIdentity("support_email", event.target.value)} maxLength={254} />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="setup-support-phone">Số điện thoại hỗ trợ</Label>
          <Input id="setup-support-phone" className={inputClassName} value={identity?.support_phone ?? ""} onChange={(event) => updateIdentity("support_phone", event.target.value)} maxLength={32} />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="setup-website">Website</Label>
          <Input id="setup-website" type="url" className={inputClassName} value={identity?.website_url ?? ""} onChange={(event) => updateIdentity("website_url", event.target.value)} maxLength={500} />
        </div>
        <div className="grid gap-2 sm:col-span-2">
          <Label htmlFor="setup-address">Địa chỉ</Label>
          <Input id="setup-address" className={inputClassName} value={identity?.address ?? ""} onChange={(event) => updateIdentity("address", event.target.value)} maxLength={500} />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="setup-primary-color">Màu chính</Label>
          <Input id="setup-primary-color" className={inputClassName} value={branding?.primary_color ?? ""} onChange={(event) => updateBranding("primary_color", event.target.value)} pattern="#[0-9a-fA-F]{6}" placeholder="#000000" />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="setup-secondary-color">Màu phụ</Label>
          <Input id="setup-secondary-color" className={inputClassName} value={branding?.secondary_color ?? ""} onChange={(event) => updateBranding("secondary_color", event.target.value)} pattern="#[0-9a-fA-F]{6}" placeholder="#000000" />
        </div>
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
      catalog.packs.find((pack) => pack.key === selectedPackKey)?.terminology_keys ?? [],
    [catalog.packs, selectedPackKey],
  );
  const current = value ?? { locale: "", timezone: "", currency: "", terminology: {} };
  return (
    <fieldset className="grid gap-5">
      <legend className="sr-only">Khu vực và thuật ngữ</legend>
      <p className="text-sm leading-6 text-muted-foreground">
        Chỉ các giá trị được máy chủ hỗ trợ mới có thể lưu. Không có khu vực hoặc tiền tệ mặc định.
      </p>
      <StepIssues issues={issues} />
      {!selectedPackKey ? (
        <Alert>
          <AlertTitle>Chưa chọn gói ngành</AlertTitle>
          <AlertDescription>
            Hãy chọn gói ngành ở bước trước để tải đúng bộ thuật ngữ.
          </AlertDescription>
        </Alert>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor="setup-locale">Ngôn ngữ *</Label>
          <select id="setup-locale" className={selectClassName} value={current.locale} onChange={(event) => onChange({ ...current, locale: event.target.value })} required autoFocus>
            <option value="">Chọn ngôn ngữ</option>
            {catalog.locales.map((locale) => <option key={locale} value={locale}>{locale}</option>)}
          </select>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="setup-currency">Tiền tệ *</Label>
          <select id="setup-currency" className={selectClassName} value={current.currency} onChange={(event) => onChange({ ...current, currency: event.target.value })} required>
            <option value="">Chọn tiền tệ</option>
            {catalog.currencies.map((currency) => <option key={currency} value={currency}>{currency}</option>)}
          </select>
        </div>
        <div className="grid gap-2 sm:col-span-2">
          <Label htmlFor="setup-timezone">Múi giờ IANA *</Label>
          <Input id="setup-timezone" className={inputClassName} value={current.timezone} onChange={(event) => onChange({ ...current, timezone: event.target.value })} placeholder="Continent/City" required maxLength={64} />
        </div>
        {terminologyKeys.map((key) => (
          <div key={key} className="grid gap-2">
            <Label htmlFor={`term-${key}`}>Thuật ngữ: {key}</Label>
            <Input id={`term-${key}`} className={inputClassName} value={current.terminology[key] ?? ""} onChange={(event) => onChange({ ...current, terminology: { ...current.terminology, [key]: event.target.value } })} maxLength={80} />
          </div>
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
  const selectedPack = catalog.packs.find((pack) => pack.key === value?.pack_key);
  return (
    <fieldset className="grid gap-5">
      <legend className="sr-only">Gói ngành và chức năng</legend>
      <StepIssues issues={issues} />
      <div className="grid gap-3 sm:grid-cols-2">
        {catalog.packs.map((pack) => (
          <label key={pack.key} className="flex min-h-20 cursor-pointer items-start gap-3 rounded-lg border bg-card p-4 focus-within:ring-3 focus-within:ring-ring/50">
            <input type="radio" name="setup-pack" value={pack.key} checked={value?.pack_key === pack.key} onChange={() => onChange({ pack_key: pack.key, capability_ids: [] })} className="mt-1 size-4" />
            <span className="min-w-0"><strong className="block break-words">{pack.key}</strong><span className="text-xs text-muted-foreground">Phiên bản {pack.version}</span></span>
          </label>
        ))}
      </div>
      {selectedPack ? (
        <div className="grid gap-3">
          <h3 className="font-medium">Chức năng cho phép</h3>
          {selectedPack.capability_ids.map((capabilityId) => {
            const checked = value?.capability_ids.includes(capabilityId) ?? false;
            return (
              <label key={capabilityId} className="flex min-h-11 items-center gap-3 rounded-md border px-3 py-2">
                <Checkbox checked={checked} onCheckedChange={(next) => onChange({ pack_key: selectedPack.key, capability_ids: next === true ? [...(value?.capability_ids ?? []), capabilityId] : (value?.capability_ids ?? []).filter((item) => item !== capabilityId) })} />
                <span className="break-all text-sm">{capabilityId}</span>
              </label>
            );
          })}
        </div>
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
  const retainIncompleteLocalSelection = useRef(false);
  const [handoffMode, setHandoffMode] = useState<"" | WorkflowDraft["workflow_policy"]["handoff_mode"]>(initial?.handoff_mode ?? "");
  const [automationChoice, setAutomationChoice] = useState<"" | "enabled" | "disabled">(
    initial ? (initial.automation_enabled ? "enabled" : "disabled") : "",
  );
  const allowedIds = useMemo(
    () => catalog.packs.find((pack) => pack.key === selectedPackKey)?.workflow_ids ?? [],
    [catalog.packs, selectedPackKey],
  );
  const workflows = useMemo(
    () => catalog.workflows.filter((workflow) => allowedIds.includes(workflow.id)),
    [allowedIds, catalog.workflows],
  );
  const selectedWorkflow = workflows.find((workflow) => workflow.id === workflowId);
  useEffect(() => {
    const policy = value?.workflow_policy;
    if (!policy && retainIncompleteLocalSelection.current) {
      retainIncompleteLocalSelection.current = false;
      return;
    }
    const version = catalog.authored_workflow_versions.find(
      (candidate) =>
        candidate.id === policy?.workflow_version_id &&
        candidate.checksum === policy.workflow_version_checksum &&
        candidate.pack_key === selectedPackKey &&
        candidate.workflow_key === policy.workflow_id,
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
  }, [allowedIds, catalog.authored_workflow_versions, selectedPackKey, syncToken, value]);
  const selectableVersions = authoredVersions
    .filter(
      (version) =>
        version.pack_key === selectedPackKey && version.workflow_key === workflowId,
    )
    .sort((left, right) => right.version_no - left.version_no);
  const reloadVersions = async () => {
    setVersionError(null);
    try {
      const versions = await listWorkflowVersions();
      setAuthoredVersions(versions);
    } catch (cause) {
      setVersionError(
        cause instanceof Error ? cause.message : "Không tải lại được phiên bản quy trình.",
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
    if (!nextWorkflowId || !version || !nextHandoffMode || !nextAutomationChoice) {
      retainIncompleteLocalSelection.current = Boolean(value);
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
    <fieldset className="grid gap-5">
      <legend className="sr-only">Quy trình và bàn giao</legend>
      <StepIssues issues={issues} />
      {!selectedPackKey ? <Alert><AlertTitle>Chưa chọn gói</AlertTitle><AlertDescription>Hãy chọn gói ở bước trước để tải đúng quy trình.</AlertDescription></Alert> : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2 sm:col-span-2">
          <Label htmlFor="setup-workflow">Quy trình *</Label>
          <select id="setup-workflow" className={selectClassName} value={workflowId} onChange={(event) => { const next = event.target.value; setWorkflowId(next); setWorkflowVersionId(""); setHandoffMode(""); commit(next, "", "", automationChoice); }} required autoFocus>
            <option value="">Chọn quy trình</option>
            {workflows.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflow.id}</option>)}
          </select>
        </div>
        <div className="grid gap-2 sm:col-span-2">
          <Label htmlFor="setup-workflow-version">Phiên bản đã xuất bản *</Label>
          <select
            id="setup-workflow-version"
            className={selectClassName}
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
          {workflowId && selectableVersions.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Chưa có phiên bản nào. Hãy tạo và xuất bản một phiên bản bên dưới.
            </p>
          ) : null}
          {versionError ? <p className="text-sm text-destructive" role="alert">{versionError}</p> : null}
        </div>
        <div className="grid gap-2">
          <Label htmlFor="setup-handoff">Cách bàn giao *</Label>
          <select id="setup-handoff" className={selectClassName} value={handoffMode} onChange={(event) => { const next = event.target.value as "" | WorkflowDraft["workflow_policy"]["handoff_mode"]; setHandoffMode(next); commit(workflowId, workflowVersionId, next, automationChoice); }} required>
            <option value="">Chọn cách bàn giao</option>
            {(selectedWorkflow?.handoff_modes ?? []).map((mode) => <option key={mode} value={mode}>{mode === "manual" ? "Thủ công" : mode === "assisted" ? "Có hỗ trợ" : "Tự động"}</option>)}
          </select>
        </div>
        <fieldset className="grid gap-2 sm:col-span-2">
          <legend className="text-sm font-medium">Tự động hóa *</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="flex min-h-11 items-center gap-3 rounded-md border px-3 py-2 text-sm"><input type="radio" name="setup-automation" checked={automationChoice === "enabled"} onChange={() => { setAutomationChoice("enabled"); commit(workflowId, workflowVersionId, handoffMode, "enabled"); }} />Bật tự động hóa</label>
            <label className="flex min-h-11 items-center gap-3 rounded-md border px-3 py-2 text-sm"><input type="radio" name="setup-automation" checked={automationChoice === "disabled"} onChange={() => { setAutomationChoice("disabled"); commit(workflowId, workflowVersionId, handoffMode, "disabled"); }} />Không bật tự động hóa</label>
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

const cleanKey = (value: string) => value.trim().toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");

export const KnowledgeTemplatesStep = ({
  value,
  onChange,
  issues,
}: CommonStepProps & {
  value?: KnowledgeTemplatesDraft;
  onChange: (value: KnowledgeTemplatesDraft) => void;
}) => {
  const [templates, setTemplates] = useState<SetupTemplate[]>([]);
  const [versions, setVersions] = useState<SetupTemplateVersion[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [name, setName] = useState("");
  const [vertical, setVertical] = useState("");
  const [recordName, setRecordName] = useState("");
  const [fields, setFields] = useState("");
  const [sample, setSample] = useState("");
  const [previewed, setPreviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => {
    setError(null);
    try { setTemplates(await listSetupTemplates()); } catch (cause) { setError(cause instanceof Error ? cause.message : "Không tải được danh sách mẫu."); }
  };
  useEffect(() => { void reload(); }, []);

  const selectTemplate = async (templateId: string) => {
    setSelectedTemplateId(templateId);
    setVersions([]);
    if (!templateId) return;
    try { setVersions((await listSetupTemplateVersions(templateId)).filter((item) => item.status === "PUBLISHED" && item.checksum)); } catch (cause) { setError(cause instanceof Error ? cause.message : "Không tải được phiên bản mẫu."); }
  };
  const toggleVersion = (version: SetupTemplateVersion, checked: boolean) => {
    if (!version.checksum) return;
    const current = value?.template_version_refs ?? [];
    onChange({ template_version_refs: checked ? [...current.filter((item) => item.version_id !== version.id), { version_id: version.id, checksum: version.checksum }] : current.filter((item) => item.version_id !== version.id) });
  };
  const buildDefinition = (): Record<string, unknown> | null => {
    const recordKey = cleanKey(recordName);
    const fieldKeys = fields.split(",").map(cleanKey).filter(Boolean);
    if (!recordKey || fieldKeys.length === 0) return null;
    return { schema_version: "1", record_types: [{ key: recordKey, display_name: recordName.trim(), natural_key_fields: [fieldKeys[0]], fields: fieldKeys.map((key, index) => ({ key, type: "string", aliases: [key, key.replace(/_/g, " ")], required: index === 0, source_mode: "sourced_fact" })) }] };
  };
  const preview = async () => {
    const definition = buildDefinition();
    if (!name.trim() || !vertical.trim() || !definition || !sample.trim()) { setError("Nhập đủ tên mẫu, lĩnh vực, loại bản ghi, trường dữ liệu và dữ liệu thử."); return; }
    setBusy(true); setError(null);
    try { await previewNewSetupTemplate(definition, sample); setPreviewed(true); } catch (cause) { setError(cause instanceof Error ? cause.message : "Không kiểm tra được mẫu."); } finally { setBusy(false); }
  };
  const publish = async () => {
    const definition = buildDefinition();
    if (!previewed || !definition) return;
    setBusy(true); setError(null);
    try {
      const created = await createSetupTemplate({ template_key: `${cleanKey(name)}_${Date.now()}`, name: name.trim(), vertical: vertical.trim(), definition });
      await previewSetupTemplateVersion(created.id, sample);
      const published = await publishSetupTemplateVersion(created.id);
      if (!published.checksum) throw new Error("Phiên bản đã xuất bản thiếu checksum.");
      toggleVersion(published, true);
      setName(""); setVertical(""); setRecordName(""); setFields(""); setSample(""); setPreviewed(false);
      await reload();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Không xuất bản được mẫu."); } finally { setBusy(false); }
  };

  return (
    <div className="grid gap-6">
      <StepIssues issues={issues} />
      <section className="grid gap-4 rounded-lg border p-4 sm:p-5" aria-labelledby="existing-template-title">
        <h3 id="existing-template-title" className="font-semibold">Chọn mẫu đã xuất bản</h3>
        <select className={selectClassName} aria-label="Mẫu kiến thức" value={selectedTemplateId} onChange={(event) => void selectTemplate(event.target.value)}>
          <option value="">Chọn mẫu</option>
          {templates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}
        </select>
        {versions.map((version) => (
          <label key={version.id} className="flex min-h-11 items-center gap-3 rounded-md border px-3 py-2 text-sm">
            <Checkbox checked={value?.template_version_refs.some((item) => item.version_id === version.id) ?? false} onCheckedChange={(checked) => toggleVersion(version, checked === true)} />
            Phiên bản {version.version_no}
          </label>
        ))}
      </section>
      <section className="grid gap-4 rounded-lg border p-4 sm:p-5" aria-labelledby="new-template-title">
        <div><h3 id="new-template-title" className="font-semibold">Tạo mẫu mới</h3><p className="mt-1 text-sm text-muted-foreground">Mọi trường và dữ liệu thử đều do quản trị viên nhập.</p></div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="grid gap-2"><Label htmlFor="new-template-name">Tên mẫu</Label><Input id="new-template-name" className={inputClassName} value={name} onChange={(event) => { setName(event.target.value); setPreviewed(false); }} /></div>
          <div className="grid gap-2"><Label htmlFor="new-template-vertical">Lĩnh vực</Label><Input id="new-template-vertical" className={inputClassName} value={vertical} onChange={(event) => { setVertical(event.target.value); setPreviewed(false); }} /></div>
          <div className="grid gap-2"><Label htmlFor="new-template-record">Loại bản ghi</Label><Input id="new-template-record" className={inputClassName} value={recordName} onChange={(event) => { setRecordName(event.target.value); setPreviewed(false); }} /></div>
          <div className="grid gap-2"><Label htmlFor="new-template-fields">Các trường, cách nhau bằng dấu phẩy</Label><Input id="new-template-fields" className={inputClassName} value={fields} onChange={(event) => { setFields(event.target.value); setPreviewed(false); }} /></div>
          <div className="grid gap-2 sm:col-span-2"><Label htmlFor="new-template-sample">Dữ liệu thử của bạn</Label><Textarea id="new-template-sample" value={sample} onChange={(event) => { setSample(event.target.value); setPreviewed(false); }} rows={6} /></div>
        </div>
        {error ? <p className="text-sm text-destructive" role="alert">{error}</p> : null}
        <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="outline" className="min-h-11" disabled={busy} onClick={() => void preview()}>{busy ? <Loader2 className="animate-spin" /> : <RefreshCw />}Kiểm tra mẫu</Button>
          <Button type="button" className="min-h-11" disabled={busy || !previewed} onClick={() => void publish()}><Plus />Xuất bản và chọn</Button>
        </div>
      </section>
    </div>
  );
};

export const PersonaStep = ({
  value,
  onChange,
  issues,
}: CommonStepProps & {
  value?: PersonaDraft;
  onChange: (value: PersonaDraft) => void;
}) => {
  const [personas, setPersonas] = useState<PersonaOption[]>([]);
  const [versions, setVersions] = useState<PersonaVersionOption[]>([]);
  const [selectedPersonaId, setSelectedPersonaId] = useState("");
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [notes, setNotes] = useState("");
  const [followupDisabledConfirmed, setFollowupDisabledConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reload = async () => { try { setPersonas(await listSetupPersonas()); } catch (cause) { setError(cause instanceof Error ? cause.message : "Không tải được Agent."); } };
  useEffect(() => { void reload(); }, []);
  const selectPersona = async (personaId: string) => {
    setSelectedPersonaId(personaId); setVersions([]); if (!personaId) return;
    try { setVersions(await listSetupPersonaVersions(personaId)); } catch (cause) { setError(cause instanceof Error ? cause.message : "Không tải được phiên bản Agent."); }
  };
  const create = async () => {
    if (!name.trim() || !body.trim()) { setError("Tên và nội dung Agent là bắt buộc."); return; }
    if (!followupDisabledConfirmed) {
      setError("Hãy xác nhận tắt theo dõi chủ động trước khi tạo Agent.");
      return;
    }
    setBusy(true); setError(null);
    try {
      const persona = await createSetupPersona({
        name: name.trim(),
        body_md: body.trim(),
        notes: optional(notes) ?? null,
        followup_rules: disabledSetupFollowupRules(),
      });
      const nextVersions = await listSetupPersonaVersions(persona.id);
      const latest = nextVersions.sort((a, b) => b.version_no - a.version_no)[0];
      if (!latest) throw new Error("Agent chưa có phiên bản bất biến.");
      onChange({ persona_version_id: latest.id, checksum: latest.checksum });
      setName(""); setBody(""); setNotes(""); setFollowupDisabledConfirmed(false); await reload(); await selectPersona(persona.id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Không tạo được Agent."); } finally { setBusy(false); }
  };
  return (
    <div className="grid gap-6">
      <StepIssues issues={issues} />
      <section className="grid gap-4 rounded-lg border p-4 sm:p-5">
        <h3 className="font-semibold">Chọn phiên bản Agent</h3>
        <select className={selectClassName} value={selectedPersonaId} onChange={(event) => void selectPersona(event.target.value)} aria-label="Agent">
          <option value="">Chọn Agent</option>{personas.map((persona) => <option key={persona.id} value={persona.id}>{persona.name}</option>)}
        </select>
        <div className="grid gap-2 sm:grid-cols-2">
          {versions.map((version) => (
            <Button key={version.id} type="button" variant={value?.persona_version_id === version.id ? "default" : "outline"} className="min-h-11 justify-start" onClick={() => onChange({ persona_version_id: version.id, checksum: version.checksum })}>
              {value?.persona_version_id === version.id ? <Check /> : null}Phiên bản {version.version_no}
            </Button>
          ))}
        </div>
      </section>
      <section className="grid gap-4 rounded-lg border p-4 sm:p-5">
        <div><h3 className="font-semibold">Tạo Agent mới</h3><p className="mt-1 text-sm text-muted-foreground">Không có nội dung mẫu. Hãy viết persona và chính sách phù hợp với khách hàng này.</p></div>
        <div className="grid gap-2"><Label htmlFor="new-persona-name">Tên Agent *</Label><Input id="new-persona-name" className={inputClassName} value={name} onChange={(event) => setName(event.target.value)} /></div>
        <div className="grid gap-2"><Label htmlFor="new-persona-body">Nội dung và chính sách *</Label><Textarea id="new-persona-body" value={body} onChange={(event) => setBody(event.target.value)} rows={10} /></div>
        <div className="grid gap-2"><Label htmlFor="new-persona-notes">Ghi chú</Label><Textarea id="new-persona-notes" value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} /></div>
        <label className="flex min-h-11 items-start gap-3 rounded-md border p-3 text-sm">
          <Checkbox
            checked={followupDisabledConfirmed}
            onCheckedChange={(checked) => setFollowupDisabledConfirmed(checked === true)}
            aria-describedby="new-persona-followup-help"
          />
          <span className="grid gap-1">
            <span className="font-medium">Xác nhận tắt theo dõi chủ động</span>
            <span id="new-persona-followup-help" className="leading-5 text-muted-foreground">
              Hệ thống sẽ không tạo lịch hoặc gửi tin nhắn theo dõi chủ động. Quy tắc theo dõi chỉ có thể được cấu hình khi tính năng tương ứng được hỗ trợ.
            </span>
          </span>
        </label>
        {error ? <p className="text-sm text-destructive" role="alert">{error}</p> : null}
        <Button type="button" className="min-h-11 sm:justify-self-end" disabled={busy || !followupDisabledConfirmed} onClick={() => void create()}>{busy ? <Loader2 className="animate-spin" /> : <Plus />}Tạo và chọn phiên bản</Button>
      </section>
    </div>
  );
};

const ProviderSecretPanel = ({ integrationKey }: { integrationKey: SupportedModelIntegration }) => {
  const [configured, setConfigured] = useState(false);
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void getModelIntegrationStatus(integrationKey).then((status) => {
      if (!active) return;
      setConfigured(
        "minimax_api_key" in status
          ? status.minimax_api_key.configured
          : status.openrouter_api_key.configured,
      );
    }).catch(() => { if (active) setMessage("Không tải được trạng thái tích hợp."); });
    return () => { active = false; };
  }, [integrationKey]);
  const save = async () => {
    if (!secret.trim()) return;
    setBusy(true); setMessage(null);
    try { await saveModelIntegrationSecret(integrationKey, secret.trim()); setSecret(""); setConfigured(true); setMessage("Đã lưu bí mật ở dạng mã hóa."); } catch (cause) { setMessage(cause instanceof Error ? cause.message : "Không lưu được bí mật."); } finally { setBusy(false); }
  };
  const test = async () => {
    setBusy(true); setMessage(null);
    try { const result = await testModelIntegration(integrationKey); setMessage(result.configured ? "Tích hợp đã sẵn sàng." : `Thiếu: ${result.missing.join(", ")}`); } catch (cause) { setMessage(cause instanceof Error ? cause.message : "Không kiểm tra được tích hợp."); } finally { setBusy(false); }
  };
  return (
    <section className="grid gap-3 rounded-lg border p-4">
      <div><h4 className="font-medium">{integrationKey}</h4><p className="text-xs text-muted-foreground">{configured ? "Đã có khóa được mã hóa" : "Chưa có khóa"}</p></div>
      <Label htmlFor={`secret-${integrationKey}`}>Khóa bí mật</Label>
      <Input id={`secret-${integrationKey}`} type="password" autoComplete="off" className={inputClassName} value={secret} onChange={(event) => setSecret(event.target.value)} />
      <div className="flex flex-col gap-2 sm:flex-row"><Button type="button" className="min-h-11" disabled={busy || !secret.trim()} onClick={() => void save()}>Lưu khóa</Button><Button type="button" variant="outline" className="min-h-11" disabled={busy || !configured} onClick={() => void test()}>Kiểm tra</Button></div>
      {message ? <p className="text-sm" aria-live="polite">{message}</p> : null}
    </section>
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
  const [status, setStatus] = useState<Awaited<ReturnType<typeof getZaloSetupStatus>> | null>(null);
  const [form, setForm] = useState<ZaloSecretDraft>(EMPTY_ZALO_SECRETS);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void getZaloSetupStatus()
      .then((next) => { if (active) setStatus(next); })
      .catch(() => { if (active) setMessage("Không tải được trạng thái Zalo."); });
    return () => { active = false; };
  }, []);
  const setField = (field: keyof ZaloSecretDraft, next: string) =>
    setForm((current) => ({ ...current, [field]: next }));
  const save = async () => {
    const payload = Object.fromEntries(
      Object.entries(form).filter(([, value]) => value.trim()),
    ) as Partial<ZaloSecretDraft>;
    if (Object.keys(payload).length === 0) return;
    setBusy(true); setMessage(null);
    try {
      setStatus(await saveZaloSetupSecrets(payload));
      setForm(EMPTY_ZALO_SECRETS);
      setMessage("Đã lưu thông tin Zalo ở kho mã hóa.");
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : "Không lưu được Zalo."); }
    finally { setBusy(false); }
  };
  const test = async (channel: "bot" | "oa") => {
    setBusy(true); setMessage(null);
    try {
      const result = await testZaloSetupChannel(channel);
      setMessage(result.connected ? `Kênh ${channel.toUpperCase()} đã kết nối.` : result.missing.length > 0 ? `Thiếu: ${result.missing.join(", ")}` : result.errors.join("; ") || "Kênh chưa kết nối.");
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : "Không kiểm tra được Zalo."); }
    finally { setBusy(false); }
  };
  const fields: Array<{ key: keyof ZaloSecretDraft; label: string; secret: boolean }> = [
    { key: "zalo_bot_token", label: "Bot token", secret: true },
    { key: "zalo_bot_webhook_secret", label: "Bot webhook secret", secret: true },
    { key: "zalo_oa_app_id", label: "OA App ID", secret: false },
    { key: "zalo_oa_secret_key", label: "OA secret key", secret: true },
    { key: "zalo_oa_access_token", label: "OA access token", secret: true },
    { key: "zalo_oa_refresh_token", label: "OA refresh token", secret: true },
  ];
  const configuredCount = status
    ? [status.zalo_bot_token, status.zalo_bot_webhook_secret, status.zalo_oa_app_id, status.zalo_oa_secret_key, status.zalo_oa_access_token, status.zalo_oa_refresh_token].filter((item) => item.configured).length
    : 0;
  return (
    <section className="grid gap-4 rounded-lg border p-4 sm:col-span-2" aria-labelledby="setup-zalo-title">
      <div><h4 id="setup-zalo-title" className="font-medium">Zalo</h4><p className="text-xs text-muted-foreground">{configuredCount}/6 trường đã cấu hình. Giá trị bí mật đã lưu không được tải lại vào biểu mẫu.</p></div>
      <div className="grid gap-4 sm:grid-cols-2">
        {fields.map((field) => (
          <div key={field.key} className="grid gap-2">
            <Label htmlFor={`zalo-${field.key}`}>{field.label}</Label>
            <Input id={`zalo-${field.key}`} type={field.secret ? "password" : "text"} autoComplete="off" className={inputClassName} value={form[field.key]} onChange={(event) => setField(field.key, event.target.value)} />
          </div>
        ))}
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        <Button type="button" className="min-h-11" disabled={busy || !Object.values(form).some((item) => item.trim())} onClick={() => void save()}>Lưu thông tin Zalo</Button>
        <Button type="button" variant="outline" className="min-h-11" disabled={busy} onClick={() => void test("bot")}>Kiểm tra Bot</Button>
        <Button type="button" variant="outline" className="min-h-11" disabled={busy} onClick={() => void test("oa")}>Kiểm tra OA</Button>
      </div>
      {message ? <p className="text-sm" aria-live="polite">{message}</p> : null}
    </section>
  );
};

export const ProvidersIntegrationsStep = ({
  value,
  onChange,
  catalog,
  issues,
}: CommonStepProps & {
  value?: ProvidersIntegrationsDraft;
  onChange: (value: ProvidersIntegrationsDraft) => void;
}) => {
  const [policy, setPolicy] = useState(() => ({
    chatIntegrationKey: value?.provider_policy.chat_integration_key ?? "",
    chatModel: value?.provider_policy.chat_model ?? "",
    embeddingIntegrationKey: value?.provider_policy.embedding_integration_key ?? "",
    embeddingModel: value?.provider_policy.embedding_model ?? "",
    temperature: value ? String(value.provider_policy.temperature) : "",
    maxOutputTokens: value ? String(value.provider_policy.max_output_tokens) : "",
  }));
  const selectedKeys = Array.from(
    new Set(
      [
        policy.chatIntegrationKey,
        policy.embeddingIntegrationKey,
      ].filter(Boolean),
    ),
  );
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
      <Alert><ShieldCheck /><AlertTitle>Bí mật không nằm trong bản nháp</AlertTitle><AlertDescription>Khóa được gửi thẳng đến kho mã hóa hiện có. Bản nháp chỉ lưu tham chiếu và chính sách.</AlertDescription></Alert>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2"><Label htmlFor="chat-provider">Nhà cung cấp chat *</Label><select id="chat-provider" className={selectClassName} value={policy.chatIntegrationKey} onChange={(event) => updatePolicy({ chatIntegrationKey: event.target.value })}><option value="">Chọn nhà cung cấp</option>{catalog.integration_keys.filter((key) => key === "minimax" || key === "openrouter").map((key) => <option key={key} value={key}>{key}</option>)}</select></div>
        <div className="grid gap-2"><Label htmlFor="chat-model">Model chat *</Label><Input id="chat-model" className={inputClassName} value={policy.chatModel} onChange={(event) => updatePolicy({ chatModel: event.target.value })} /></div>
        <div className="grid gap-2"><Label htmlFor="embedding-provider">Nhà cung cấp embedding *</Label><select id="embedding-provider" className={selectClassName} value={policy.embeddingIntegrationKey} onChange={(event) => updatePolicy({ embeddingIntegrationKey: event.target.value })}><option value="">Chọn nhà cung cấp</option>{catalog.integration_keys.filter((key) => key === "openrouter").map((key) => <option key={key} value={key}>{key}</option>)}</select></div>
        <div className="grid gap-2"><Label htmlFor="embedding-model">Model embedding *</Label><Input id="embedding-model" className={inputClassName} value={policy.embeddingModel} onChange={(event) => updatePolicy({ embeddingModel: event.target.value })} /></div>
        <div className="grid gap-2"><Label htmlFor="temperature">Temperature *</Label><Input id="temperature" type="number" min={0} max={2} step="0.1" className={inputClassName} value={policy.temperature} onChange={(event) => updatePolicy({ temperature: event.target.value })} /></div>
        <div className="grid gap-2"><Label htmlFor="max-output">Số token đầu ra tối đa *</Label><Input id="max-output" type="number" min={1} max={131072} className={inputClassName} value={policy.maxOutputTokens} onChange={(event) => updatePolicy({ maxOutputTokens: event.target.value })} /></div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {selectedKeys.filter(isSupportedModelIntegration).map((key) => <ProviderSecretPanel key={key} integrationKey={key} />)}
        {selectedKeys.includes("zalo") ? <ZaloSecretPanel /> : null}
      </div>
      <label className="flex min-h-11 items-center gap-3 rounded-md border px-3 py-2 text-sm"><Checkbox checked={true} disabled />Email và mật khẩu (phương thức quản trị duy nhất được hỗ trợ)</label>
    </fieldset>
  );
};
