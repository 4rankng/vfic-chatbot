import type { Lead } from "../../types";

export interface LeadDirectoryPort {
  listByZaloIds(
    zaloIds: string[],
    signal?: AbortSignal,
  ): Promise<Lead[]>;
}

export interface LeadRealtimePort {
  subscribeToLeadUpdates(
    leadId: string | number,
    onUpdate: (payload: {
      id?: string | number;
      lead_id?: string | number;
      zalo_id?: string | null;
    }) => void,
  ): () => void;
}
