import { apiJson } from "@/lib/apiClient";
import type { Lead } from "../../types";
import type {
  CancellationSignal,
  LeadDirectoryPort,
} from "../application/ports";

type LeadListEnvelope = {
  data: Lead[];
  total: number;
};

const listLeads = async (
  params: Record<string, string>,
  signal?: CancellationSignal,
): Promise<Lead[]> => {
  const search = new URLSearchParams(params);
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
};

export const leadDirectoryApi: LeadDirectoryPort = {
  async listByZaloIds(zaloIds, signal) {
    if (zaloIds.length === 0) return [];
    return listLeads(
      { zalo_ids: zaloIds.join(","), per_page: String(zaloIds.length) },
      signal,
    );
  },
  async listByContactIds(contactIds, signal) {
    if (contactIds.length === 0) return [];
    return listLeads(
      {
        contact_ids: contactIds.join(","),
        per_page: String(contactIds.length),
      },
      signal,
    );
  },
};
