import type { LeadRealtimePort } from "../application/ports";

type LeadRealtimeSocket = {
  connected: boolean;
  connect(): void;
  emit(event: string, payload: { lead_id: string | number }): void;
  on(
    event: "lead.updated",
    listener: (payload: {
      id?: string | number;
      lead_id?: string | number;
      zalo_id?: string | null;
    }) => void,
  ): void;
  off(
    event: "lead.updated",
    listener: (payload: {
      id?: string | number;
      lead_id?: string | number;
      zalo_id?: string | null;
    }) => void,
  ): void;
};

export const createLeadRealtimePort = (
  socket: LeadRealtimeSocket,
): LeadRealtimePort => ({
  subscribeToLeadUpdates(leadId, onUpdate) {
    socket.on("lead.updated", onUpdate);
    if (!socket.connected) socket.connect();
    socket.emit("join lead", { lead_id: leadId });
    return () => {
      socket.off("lead.updated", onUpdate);
      socket.emit("leave lead", { lead_id: leadId });
    };
  },
});
