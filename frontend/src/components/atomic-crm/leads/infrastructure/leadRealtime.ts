import type { LeadRealtimePort } from "../application/ports";

type LeadUpdatedListener = (payload: {
  id?: string | number;
  lead_id?: string | number;
  zalo_id?: string | null;
}) => void;

/** The Socket.IO surface the lead port needs (a realtime socket satisfies it). */
export type LeadRealtimeSocket = {
  connected: boolean;
  connect(): void;
  emit(
    event: "join lead" | "leave lead",
    payload: { lead_id: string | number },
  ): void;
  on(event: "lead.updated", listener: LeadUpdatedListener): void;
  on(event: "connect", listener: () => void): void;
  off(event: "lead.updated", listener: LeadUpdatedListener): void;
  off(event: "connect", listener: () => void): void;
};

export const createLeadRealtimePort = (
  socket: LeadRealtimeSocket,
): LeadRealtimePort => ({
  subscribeToLeadUpdates(leadId, onUpdate) {
    // Room membership is per connection: the server drops it whenever the
    // socket re-handshakes (network blip, or the re-auth after a rotated JWT),
    // so the room is joined both on subscribe and on every `connect`. The
    // `connect` event fires only after the server accepted the auth handshake,
    // i.e. the join always travels with the current token. Joining twice is
    // harmless — the server adds to a set.
    const join = () => socket.emit("join lead", { lead_id: leadId });
    socket.on("lead.updated", onUpdate);
    socket.on("connect", join);
    // Emits made before the socket connects are buffered and flushed on
    // connect, so this join still lands when subscribed while offline.
    if (!socket.connected) socket.connect();
    join();
    return () => {
      socket.off("lead.updated", onUpdate);
      socket.off("connect", join);
      socket.emit("leave lead", { lead_id: leadId });
    };
  },
});
