import { apiJson } from "../../providers/rest/api";
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
    const response = await apiJson<LeadListEnvelope>(
      `/api/v1/leads?${search.toString()}`,
      { signal },
    );
    return response.data;
  },
};
