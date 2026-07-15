import { useEffect, useRef, useState } from "react";
import { required, useInput } from "ra-core";
import { useFormContext } from "react-hook-form";

import { Create } from "@/components/admin/create";
import { AutocompleteInput } from "@/components/admin/autocomplete-input";
import { Edit } from "@/components/admin/edit";
import { BooleanInput } from "@/components/admin/boolean-input";
import { DateInput } from "@/components/admin/date-input";
import { DateTimeInput } from "@/components/admin/date-time-input";
import { NumberInput } from "@/components/admin/number-input";
import { ReferenceInput } from "@/components/admin/reference-input";
import { SelectInput } from "@/components/admin/select-input";
import { SimpleForm } from "@/components/admin/simple-form";
import { TextInput } from "@/components/admin/text-input";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Label } from "@/components/ui/label";
import {
  getWorkflowVersion,
  listWorkflowVersions,
  type CaseAttributeDefinition,
  type WorkflowVersionDetail,
  type WorkflowVersionSummary,
} from "../workflows/workflow-authoring-client";
import { useCompiledRuntime } from "../capabilities/runtime-context";

const selectClassName =
  "min-h-11 w-full rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

const WorkflowVersionInput = () => {
  const { packKey } = useCompiledRuntime();
  const form = useFormContext();
  const versionInput = useInput({ source: "workflow_version_id", validate: required() });
  const checksumInput = useInput({ source: "workflow_checksum" });
  const [versions, setVersions] = useState<WorkflowVersionSummary[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [definition, setDefinition] = useState<WorkflowVersionDetail | null>(null);
  const [loadingDefinition, setLoadingDefinition] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectionRequest = useRef(0);

  useEffect(() => {
    let active = true;
    void listWorkflowVersions({ packKey })
      .then((items) => {
        if (active) setVersions(items);
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : "Không tải được phiên bản quy trình.");
        }
      });
    return () => {
      active = false;
    };
  }, [packKey]);

  const selectVersion = async (versionId: string) => {
    const request = ++selectionRequest.current;
    setSelectedVersionId(versionId);
    setDefinition(null);
    setError(null);
    form.setValue("attributes", {});
    versionInput.field.onChange("");
    checksumInput.field.onChange("");
    if (!versionId) return;
    setLoadingDefinition(true);
    try {
      const selected = versions.find((version) => version.id === versionId);
      if (!selected) throw new Error("Phiên bản quy trình không còn khả dụng.");
      const detail = await getWorkflowVersion(versionId);
      if (request !== selectionRequest.current) return;
      if (detail.pack_key !== packKey || detail.checksum !== selected.checksum) {
        throw new Error("Phiên bản quy trình không khớp với gói đang sử dụng.");
      }
      setDefinition(detail);
      versionInput.field.onChange(detail.id);
      checksumInput.field.onChange(detail.checksum);
    } catch (cause) {
      if (request !== selectionRequest.current) return;
      setSelectedVersionId("");
      setError(cause instanceof Error ? cause.message : "Không tải được cấu hình quy trình.");
    } finally {
      if (request === selectionRequest.current) setLoadingDefinition(false);
    }
  };

  return (
    <div className="grid gap-2">
      <Label htmlFor={versionInput.id}>Quy trình *</Label>
      <select
        id={versionInput.id}
        name={versionInput.field.name}
        className={selectClassName}
        value={selectedVersionId}
        onBlur={versionInput.field.onBlur}
        onChange={(event) => void selectVersion(event.target.value)}
        required
      >
        <option value="">Chọn quy trình và phiên bản</option>
        {versions.map((version) => (
          <option key={version.id} value={version.id}>
            {version.label} — phiên bản {version.version_no}
          </option>
        ))}
      </select>
      {loadingDefinition ? <p className="text-sm text-muted-foreground">Đang tải trường thông tin…</p> : null}
      {definition ? <CaseAttributeInputs schema={definition.case_attribute_schema} /> : null}
      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Không tải được quy trình</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
};

const validationFor = (definition: CaseAttributeDefinition) =>
  definition.required ? required() : undefined;

const CaseAttributeInputs = ({
  schema,
}: {
  schema: Record<string, CaseAttributeDefinition>;
}) => {
  const entries = Object.entries(schema);
  if (entries.length === 0) return null;
  return (
    <fieldset className="grid gap-4 rounded-md border p-4">
      <legend className="px-1 text-sm font-semibold">Thông tin theo quy trình</legend>
      {entries.map(([key, definition]) => {
        const source = `attributes.${key}`;
        const validate = validationFor(definition);
        if (definition.enum?.length) {
          const choices = definition.enum.map((value) => ({ id: String(value), name: String(value) }));
          return (
            <SelectInput
              key={key}
              source={source}
              label={definition.label}
              choices={choices}
              parse={(value) => definition.enum?.find((item) => String(item) === value)}
              validate={validate}
              isRequired={definition.required}
            />
          );
        }
        switch (definition.type) {
          case "integer":
            return <NumberInput key={key} source={source} label={definition.label} step={1} validate={validate} />;
          case "number":
            return <NumberInput key={key} source={source} label={definition.label} validate={validate} />;
          case "boolean":
            return <BooleanInput key={key} source={source} label={definition.label} validate={validate} />;
          case "date":
            return <DateInput key={key} source={source} label={definition.label} validate={validate} />;
          case "datetime":
            return <DateTimeInput key={key} source={source} label={definition.label} validate={validate} />;
          case "string":
            return <TextInput key={key} source={source} label={definition.label} maxLength={definition.max_length} validate={validate} />;
        }
      })}
    </fieldset>
  );
};

const CreateFields = () => (
  <>
    <ReferenceInput source="contact_id" reference="contacts">
      <AutocompleteInput label="Liên hệ *" />
    </ReferenceInput>
    <WorkflowVersionInput />
    <TextInput source="subject" label="Tiêu đề" />
    <ReferenceInput
      source="assigned_user_id"
      reference="users"
    >
      <AutocompleteInput label="Người phụ trách" />
    </ReferenceInput>
  </>
);

export const CaseCreate = () => (
  <Create title="Tạo hồ sơ công việc">
    <SimpleForm>
      <CreateFields />
    </SimpleForm>
  </Create>
);

export const CaseEdit = () => (
  <Edit title="Cập nhật hồ sơ" actions={false}>
    <SimpleForm>
      <TextInput source="version" label="Phiên bản" readOnly className="hidden" />
      <TextInput source="subject" label="Tiêu đề" />
    </SimpleForm>
  </Edit>
);
