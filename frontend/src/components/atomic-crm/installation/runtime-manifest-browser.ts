import { apiUrl } from "@/lib/apiClient";
import type {
  RuntimeManifestGateway,
  RuntimeManifestHttpResponse,
} from "./runtime-manifest-application";

const readRuntimeManifestResponse = async (
  timeoutMs: number,
): Promise<RuntimeManifestHttpResponse> => {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(apiUrl("/api/v1/installation/runtime"), {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      credentials: "same-origin",
      signal: controller.signal,
    });
    return {
      ok: response.ok,
      status: response.status,
      cacheControl: response.headers.get("Cache-Control"),
      json: async () => response.json(),
    };
  } finally {
    window.clearTimeout(timeout);
  }
};

export const createBrowserRuntimeManifestGateway =
  (): RuntimeManifestGateway => ({
    readRuntimeManifest: async ({ timeoutMs }) =>
      readRuntimeManifestResponse(timeoutMs),
  });
