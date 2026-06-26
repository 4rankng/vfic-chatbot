// Singleton Socket.IO client for realtime chat (replaces the SSE EventSource).
//
// One socket serves the whole inbox: conversations are server-side rooms, so a
// subscription just joins/leaves a `conv:<id>` room. The access JWT rides in
// the `auth` handshake and is re-read on every (re)connect, so a refreshed
// token after expiry is picked up without re-creating the socket. autoConnect
// is false — the socket is opened lazily by the first subscriber (and only when
// a session token exists), avoiding reconnect spam when logged out.

import { getAccessToken } from "@/components/atomic-crm/providers/rest/api";

import { io, type Socket } from "socket.io-client";

import { vficConfig } from "./config";

let socket: Socket | null = null;

/**
 * Lazily create (or return the existing) realtime socket. The auth callback is
 * invoked by socket.io-client at each connection attempt, so it always sends
 * the current access token.
 */
export const getRealtimeSocket = (): Socket => {
  if (socket) return socket;
  const options = {
    auth: (cb: (data: { token: string | null }) => void) =>
      cb({ token: getAccessToken() }),
    transports: ["websocket", "polling"],
    autoConnect: false,
    reconnection: true,
  };
  const base = vficConfig.socketUrl;
  socket = base ? io(base, options) : io(options);
  return socket;
};

/** Disconnect and drop the singleton (e.g. on logout). Safe to call when idle. */
export const closeRealtimeSocket = (): void => {
  if (!socket) return;
  socket.removeAllListeners();
  socket.disconnect();
  socket = null;
};
