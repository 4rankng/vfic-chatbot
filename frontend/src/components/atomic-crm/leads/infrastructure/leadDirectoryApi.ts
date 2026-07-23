import { apiJson } from "@/lib/apiClient";
import type { Lead } from "../../types";
import type { LeadDirectoryPort } from "../application/ports";

type LeadListEnvelope = {
  data: Lead[];
  total: number;
};

export const leadDirectoryApi: LeadDirectoryPort = {
  async listByZaloIds(zaloIds, signal) {
    if (zaloIds.length === 0) return [];
    const search = new URLSearchParams({
      zalo_ids: zaloIds.join(","),
      per_page: String(zaloIds.length),
    });
    const controller = new AbortController();
    if (signal?.aborted) controller.abort();
    const dispose = signal?.onAbort(() => controller.abort());
    try {
      const response = await apiJson<LeadListEnvelope>(
        `/api/v1/leads?${search.toString()}`,
        { signal: controller.signal },
      );
      return response.data;
    } finally {
      dispose?.();
    }
  },
};
