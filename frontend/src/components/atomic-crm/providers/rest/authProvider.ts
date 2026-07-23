import type { AuthProvider, UserIdentity } from "ra-core";

import { canAccess as canAccessFn } from "../commons/canAccess";
import { closeRealtimeSocket } from "../realtime/realtime-socket";
import {
  ApiError,
  apiJson,
  clearTokens,
  getAccessToken,
  refreshOnce,
  setTokens,
} from "@/lib/apiClient";

// JWT auth provider (replaces Supabase Auth).
//
// The CRM holds only the user's access/refresh JWT pair. login exchanges
// credentials for tokens and caches the identity; getIdentity/getPermissions
// read the cache (refreshed on demand). checkError forces a re-login only when
// the backend rejects an access token that the REST client could not refresh
// (ApiError 401) — a 403 (action denied) or a reply 409 (not HUMAN) is surfaced
// by the caller, not a logout trigger.

interface TokenResponse {
  access_token: string;
  refresh_token: string;
}

interface MeResponse {
  id: string;
  email: string;
  full_name: string | null;
  role: "admin" | "recruiter";
}

const IDENTITY_KEY = "RaStore.auth.identity";

function storage(): Storage | null {
  if (typeof window !== "undefined" && window.localStorage)
    return window.localStorage;
  return null;
}

// Cached /auth/me so getIdentity/getPermissions stay sync-fast after the first
// load. Invalidated on logout and whenever the access token is gone.
const fetchIdentity = async (force = false): Promise<MeResponse | null> => {
  const store = storage();
  if (!force && store) {
    const cached = store.getItem(IDENTITY_KEY);
    if (cached) {
      try {
        return JSON.parse(cached) as MeResponse;
      } catch {
        /* fall through to refetch */
      }
    }
  }
  if (!getAccessToken()) return null;
  const me = await apiJson<MeResponse>("/api/v1/auth/me");
  store?.setItem(IDENTITY_KEY, JSON.stringify(me));
  return me;
};

const clearIdentity = (): void => {
  storage()?.removeItem(IDENTITY_KEY);
};

const clearSensitiveQueryState = async (): Promise<void> => {
  const { clearActiveDecisionTraceQueries } =
    await import("../../root/reset-runtime-state");
  clearActiveDecisionTraceQueries();
};

export const getAuthProvider = (
  availableResources: ReadonlySet<string> = new Set(),
): AuthProvider => {
  return {
    login: async (params: unknown) => {
      const { username, email, password } = params as {
        username?: string;
        email?: string;
        password: string;
      };
      const loginEmail = email ?? username;
      if (!loginEmail || !password) {
        throw new Error("Email và mật khẩu là bắt buộc");
      }
      await clearSensitiveQueryState();
      const tokens = await apiJson<TokenResponse>("/api/v1/auth/login", {
        method: "POST",
        body: { email: loginEmail, password },
      });
      setTokens(tokens.access_token, tokens.refresh_token);
      await fetchIdentity(true);
    },

    logout: async () => {
      await clearSensitiveQueryState();
      clearTokens();
      clearIdentity();
      closeRealtimeSocket();
    },

    checkAuth: async () => {
      const token = getAccessToken();
      if (!token) {
        throw new Error("Not authenticated");
      }
      // Reject locally-expired tokens without a server round-trip. This prevents
      // <CoreAdminRoutes> from rendering with a stale JWT and triggering the
      // <LogoutOnMount> → navigate → re-render infinite loop (ra-core + RR v7).
      try {
        const payload = JSON.parse(
          atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")),
        );
        if (payload.exp && payload.exp * 1000 < Date.now()) {
          // Access token expired — try a silent refresh before giving up.
          // The refresh token lives for 14 days, so this keeps the user logged
          // in across browser restarts without re-entering credentials.
          if (await refreshOnce()) {
            return; // refreshed successfully
          }
          await clearSensitiveQueryState();
          clearTokens();
          clearIdentity();
          throw new Error("Token expired");
        }
      } catch (e) {
        if (e instanceof Error && e.message === "Token expired") throw e;
        // If we can't decode (malformed), let the server decide.
      }
    },

    checkError: async (error: unknown) => {
      // The REST client already attempted a refresh on 401. Reaching here with a
      // 401 means the refresh failed too — force re-login. 403/409 etc. are
      // caller-handled (denied action / conflict), not session failures.
      if (error instanceof ApiError && error.status === 401) {
        await clearSensitiveQueryState();
        clearTokens();
        clearIdentity();
        throw error;
      }
    },

    getIdentity: async (): Promise<UserIdentity> => {
      const me = await fetchIdentity();
      if (!me) throw new Error("Not authenticated");
      return {
        id: me.id,
        fullName: me.full_name ?? me.email,
        role: me.role,
      } as UserIdentity;
    },

    getPermissions: async () => {
      const me = await fetchIdentity();
      return me?.role ?? null;
    },

    canAccess: async (params: Parameters<typeof canAccessFn>[1]) => {
      const me = await fetchIdentity();
      if (!me) return false;
      return canAccessFn(me.role, params, availableResources);
    },
  };
};

// Kept for StartPage (isInitialized gate) + the dataProvider's custom method.
// VFIC seeds the admin out-of-band, so the app is always considered initialized
// (no sign-up / first-run flow).
export const getIsInitialized = async (): Promise<boolean> => true;
