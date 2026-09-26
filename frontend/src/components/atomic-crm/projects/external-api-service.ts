// Feature-root transport for the per-project external API integration.
//
// Admin-only routes under the projects knowledge base. Bodies are passed as
// objects — `apiJson` marshals them once (see `src/lib/apiClient.ts`), so a
// pre-stringified payload would be double-encoded.

import { apiJson } from "@/lib/apiClient";

import type {
  ExternalApiTestRequest,
  ExternalApiTestResult,
  ExternalApiUpdatePayload,
  ExternalApiView,
} from "./domain/external-api-contracts";

const basePath = (projectId: string) =>
  `/api/v1/knowledge/projects/${encodeURIComponent(projectId)}/external-api`;

export const getProjectExternalApi = (projectId: string) =>
  apiJson<ExternalApiView>(basePath(projectId));

export const saveProjectExternalApi = (
  projectId: string,
  payload: ExternalApiUpdatePayload,
) =>
  apiJson<ExternalApiView>(basePath(projectId), {
    method: "PUT",
    body: payload,
  });

export const testProjectExternalApi = (
  projectId: string,
  request: ExternalApiTestRequest,
) =>
  apiJson<ExternalApiTestResult>(`${basePath(projectId)}/test`, {
    method: "POST",
    body: request,
  });
