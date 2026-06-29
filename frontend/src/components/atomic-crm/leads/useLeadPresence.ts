import { useCallback, useEffect, useRef, useState } from "react";
import { getRealtimeSocket } from "@/lib/vfic/realtimeSocket";

export interface ViewerInfo {
  user_id: string;
  name?: string;
}

interface LeadPresenceState {
  viewers: ViewerInfo[];
  typingUsers: ViewerInfo[];
}

const HEARTBEAT_INTERVAL = 15_000; // 15s — well under the 30s TTL

/**
 * Hook to join/leave a lead's Socket.IO room, broadcast presence, and listen
 * for presence.viewers / presence.typing events from other recruiters.
 *
 * Returns the current viewers and typing users so the UI can render
 * "X đang xem" indicators.
 */
export const useLeadPresence = (leadId: number | undefined) => {
  const [state, setState] = useState<LeadPresenceState>({
    viewers: [],
    typingUsers: [],
  });
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const joinRoom = useCallback(() => {
    if (!leadId) return;
    const socket = getRealtimeSocket();
    if (!socket.connected) socket.connect();
    // Join the lead room for lead.updated events
    socket.emit("join lead", { lead_id: leadId });
    // Join presence
    socket.emit("presence join", {
      entity_type: "lead",
      entity_id: leadId,
    });

    // Start heartbeat
    heartbeatRef.current = setInterval(() => {
      socket.emit("presence heartbeat", {
        entity_type: "lead",
        entity_id: leadId,
      });
    }, HEARTBEAT_INTERVAL);
  }, [leadId]);

  const leaveRoom = useCallback(() => {
    if (!leadId) return;
    const socket = getRealtimeSocket();
    socket.emit("leave lead", { lead_id: leadId });
    socket.emit("presence leave", {
      entity_type: "lead",
      entity_id: leadId,
    });
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
  }, [leadId]);

  useEffect(() => {
    if (!leadId) return;
    const socket = getRealtimeSocket();

    const onPresenceViewers = (data: {
      viewers: ViewerInfo[];
      entity_type: string;
      entity_id: string | number;
    }) => {
      if (String(data.entity_id) === String(leadId)) {
        setState((prev) => ({ ...prev, viewers: data.viewers }));
      }
    };

    const onPresenceTyping = (data: {
      entity_type: string;
      entity_id: string;
      user_id: string;
      user_name: string | null;
    }) => {
      if (data.entity_id === String(leadId)) {
        setState((prev) => {
          const others = prev.typingUsers.filter(
            (u) => u.user_id !== data.user_id,
          );
          if (data.user_name) {
            others.push({
              user_id: data.user_id,
              name: data.user_name,
            });
          }
          return { ...prev, typingUsers: others };
        });
      }
    };

    const onLeadUpdated = (data: { lead_id: number }) => {
      if (data.lead_id === leadId) {
        // Dispatch a custom event so the LeadShow component can refresh
        window.dispatchEvent(
          new CustomEvent("vfic:lead-updated", { detail: data }),
        );
      }
    };

    socket.on("presence.viewers", onPresenceViewers);
    socket.on("presence.typing", onPresenceTyping);
    socket.on("lead.updated", onLeadUpdated);

    joinRoom();

    return () => {
      socket.off("presence.viewers", onPresenceViewers);
      socket.off("presence.typing", onPresenceTyping);
      socket.off("lead.updated", onLeadUpdated);
      leaveRoom();
    };
  }, [leadId, joinRoom, leaveRoom]);

  return state;
};

/** Start a typing indicator. Caller should call the returned stop function on blur/submit. */
export const useLeadTyping = (leadId: number | undefined) => {
  const typingRef = useRef(false);
  const startTyping = useCallback(() => {
    if (!leadId || typingRef.current) return;
    typingRef.current = true;
    getRealtimeSocket().emit("presence typing", {
      entity_type: "lead",
      entity_id: String(leadId),
    });
  }, [leadId]);

  const stopTyping = useCallback(() => {
    if (!leadId || !typingRef.current) return;
    typingRef.current = false;
    getRealtimeSocket().emit("presence stop typing", {
      entity_type: "lead",
      entity_id: String(leadId),
    });
  }, [leadId]);

  return { startTyping, stopTyping };
};
