import { describe, expect, it, vi } from "vitest";

import {
  createLeadRealtimePort,
  type LeadRealtimeSocket,
} from "./leadRealtime";

type LeadUpdatedListener = (payload: {
  id?: string | number;
  lead_id?: string | number;
  zalo_id?: string | null;
}) => void;

/**
 * A room membership lives on one Socket.IO connection: the server drops it when
 * the socket re-handshakes (network blip, or the re-auth after a rotated JWT),
 * so the port must rejoin on every `connect` — the event socket.io fires only
 * once the server has accepted the auth handshake of the new connection.
 */
class FakeLeadSocket implements LeadRealtimeSocket {
  connected = false;
  readonly emitted: { event: string; leadId: string | number }[] = [];
  connectCalls = 0;
  private readonly connectListeners = new Set<() => void>();
  private readonly leadListeners = new Set<LeadUpdatedListener>();

  connect(): void {
    this.connectCalls += 1;
  }

  emit(
    event: "join lead" | "leave lead",
    payload: { lead_id: string | number },
  ): void {
    this.emitted.push({ event, leadId: payload.lead_id });
  }

  on(event: "lead.updated", listener: LeadUpdatedListener): void;
  on(event: "connect", listener: () => void): void;
  on(
    event: "lead.updated" | "connect",
    listener: LeadUpdatedListener | (() => void),
  ): void {
    if (event === "lead.updated") {
      this.leadListeners.add(listener as LeadUpdatedListener);
    } else {
      this.connectListeners.add(listener as () => void);
    }
  }

  off(event: "lead.updated", listener: LeadUpdatedListener): void;
  off(event: "connect", listener: () => void): void;
  off(
    event: "lead.updated" | "connect",
    listener: LeadUpdatedListener | (() => void),
  ): void {
    if (event === "lead.updated") {
      this.leadListeners.delete(listener as LeadUpdatedListener);
    } else {
      this.connectListeners.delete(listener as () => void);
    }
  }

  /** The server accepted a connection handshake, so `connect` fires. */
  acceptConnection(): void {
    this.connected = true;
    for (const listener of [...this.connectListeners]) listener();
  }

  dropConnection(): void {
    this.connected = false;
  }

  get connectListenerCount(): number {
    return this.connectListeners.size;
  }
}

describe("createLeadRealtimePort", () => {
  it("joins the lead room on subscribe and leaves it on unsubscribe", () => {
    const socket = new FakeLeadSocket();
    const unsubscribe = createLeadRealtimePort(socket).subscribeToLeadUpdates(
      42,
      vi.fn(),
    );

    expect(socket.connectCalls).toBe(1);
    expect(socket.emitted).toEqual([{ event: "join lead", leadId: 42 }]);

    unsubscribe();

    expect(socket.emitted).toEqual([
      { event: "join lead", leadId: 42 },
      { event: "leave lead", leadId: 42 },
    ]);
  });

  it("rejoins the lead room whenever the socket reconnects", () => {
    const socket = new FakeLeadSocket();
    const unsubscribe = createLeadRealtimePort(socket).subscribeToLeadUpdates(
      42,
      vi.fn(),
    );

    socket.acceptConnection();
    socket.dropConnection();
    socket.acceptConnection();

    expect(socket.emitted).toEqual([
      { event: "join lead", leadId: 42 },
      { event: "join lead", leadId: 42 },
      { event: "join lead", leadId: 42 },
    ]);

    unsubscribe();
  });

  it("stops rejoining after unsubscribe", () => {
    const socket = new FakeLeadSocket();
    const unsubscribe = createLeadRealtimePort(socket).subscribeToLeadUpdates(
      42,
      vi.fn(),
    );
    unsubscribe();

    expect(socket.connectListenerCount).toBe(0);
    socket.acceptConnection();

    expect(socket.emitted).toEqual([
      { event: "join lead", leadId: 42 },
      { event: "leave lead", leadId: 42 },
    ]);
  });
});
