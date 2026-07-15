import { apiJson } from "../providers/rest/api";

export type WorkflowStageDraft = {
  key: string;
  label: string;
  position: number;
  is_initial: boolean;
  is_terminal: boolean;
};

export type WorkflowVersionDraft = {
  pack_key: string;
  workflow_key: string;
  label: string;
  expected_previous_version_no?: number;
  stages: WorkflowStageDraft[];
  transitions: Array<{ from_stage_key: string; to_stage_key: string }>;
  tags: Array<{
    key: string;
    label: string;
    tone: "" | "neutral" | "info" | "success" | "warning" | "danger";
    position: number;
  }>;
  case_attribute_schema: Record<
    string,
    {
      type: "string" | "integer" | "number" | "boolean" | "date" | "datetime";
      label: string;
      required: boolean;
      max_length?: number;
      enum?: Array<string | number | boolean>;
    }
  >;
};

export type WorkflowVersionSummary = {
  id: string;
  pack_key: string;
  workflow_key: string;
  version_no: number;
  label: string;
  checksum: string;
  created_at: string;
};

export type CaseAttributeDefinition = WorkflowVersionDraft["case_attribute_schema"][string];

export type WorkflowVersionDetail = WorkflowVersionSummary & {
  schema_version: number;
  case_attribute_schema: Record<string, CaseAttributeDefinition>;
  stages: WorkflowStageDraft[];
  transitions: WorkflowVersionDraft["transitions"];
  tags: WorkflowVersionDraft["tags"];
};

export const createBlankWorkflowVersion = (): WorkflowVersionDraft => ({
  pack_key: "",
  workflow_key: "",
  label: "",
  stages: [],
  transitions: [],
  tags: [],
  case_attribute_schema: {},
});

export const listWorkflowVersions = async (filters?: {
  packKey?: string;
  workflowKey?: string;
}): Promise<WorkflowVersionSummary[]> => {
  const search = new URLSearchParams({ per_page: "200" });
  if (filters?.packKey) search.set("pack_key", filters.packKey);
  if (filters?.workflowKey) search.set("workflow_key", filters.workflowKey);
  const response = await apiJson<{ data: WorkflowVersionSummary[]; total: number }>(
    `/api/v1/admin/case-workflows?${search.toString()}`,
  );
  return response.data;
};

export const getWorkflowVersion = (versionId: string): Promise<WorkflowVersionDetail> =>
  apiJson<WorkflowVersionDetail>(`/api/v1/admin/case-workflows/${encodeURIComponent(versionId)}`);

export const publishWorkflowVersion = (
  draft: WorkflowVersionDraft,
): Promise<WorkflowVersionSummary> =>
  apiJson<WorkflowVersionSummary>("/api/v1/admin/case-workflows", {
    method: "POST",
    body: draft,
  });
