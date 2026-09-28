import type { Lead } from "../../types";

export interface CancellationSignal {
  readonly aborted: boolean;
  onAbort(listener: () => void): () => void;
}

export interface LeadDirectoryPort {
  listByZaloIds(
    zaloIds: string[],
    signal?: CancellationSignal,
  ): Promise<Lead[]>;
  listByContactIds(
    contactIds: string[],
    signal?: CancellationSignal,
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
