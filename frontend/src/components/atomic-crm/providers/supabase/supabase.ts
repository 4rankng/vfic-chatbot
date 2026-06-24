// VFIC REST client + JWT token store.
//
// Replaces the Supabase client. The CRM holds ONLY the user's access/refresh
// JWT pair (never the Zalo OA token or the LLM keys, which stay server-side).
// The access token is attached as a Bearer header on every API call; a 401
// triggers a single transparent refresh attempt (using the stored refresh
// token) before the error surfaces, so a short-lived access token expiring
// mid-session does not log the user out.

import { vficConfig } from "@/lib/vfic/config";

const ACCESS_KEY = "RaStore.auth.access_token";
const REFRESH_KEY = "RaStore.auth.refresh_token";

function storage(): Storage | null {
  if (typeof window !== "undefined" && window.localStorage) return window.localStorage;
  return null;
}

export const getAccessToken = (): string | null =>
  storage()?.getItem(ACCESS_KEY) ?? null;

export const getRefreshToken = (): string | null =>
  storage()?.getItem(REFRESH_KEY) ?? null;

export const setTokens = (accessToken: string, refreshToken: string): void => {
  storage()?.setItem(ACCESS_KEY, accessToken);
  storage()?.setItem(REFRESH_KEY, refreshToken);
};

export const clearTokens = (): void => {
  storage()?.removeItem(ACCESS_KEY);
  storage()?.removeItem(REFRESH_KEY);
};

/** Build a full URL from a path that already starts with "/api/v1/..." (or "/realtime/..."). */
export const apiUrl = (path: string): string => `${vficConfig.apiBaseUrl}${path}`;

/** Error carrying the HTTP status so callers (e.g. humanReplyService) can map it. */
export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

type Json = Record<string, unknown> | unknown[] | string | number | boolean | null;

interface RequestOptions {
  method?: string;
  body?: Json;
  /** Extra headers (Authorization is set automatically from the stored token). */
  headers?: Record<string, string>;
  /** Optional AbortSignal for fetch cancellation. */
  signal?: AbortSignal;
}

const send = async (path: string, options: RequestOptions): Promise<Response> => {
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...options.headers,
  };
  const hasBody = options.body !== undefined;
  if (hasBody && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  return fetch(apiUrl(path), {
    method: options.method ?? (hasBody ? "POST" : "GET"),
    headers,
    body: hasBody ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });
};

// Exchange the stored refresh token for a fresh access/refresh pair. Returns
// false on any failure so the caller can surface the original 401.
const refreshOnce = async (): Promise<boolean> => {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;
  try {
    const response = await fetch(apiUrl("/api/v1/auth/refresh"), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!response.ok) return false;
    const tokens = (await response.json()) as {
      access_token: string;
      refresh_token: string;
    };
    setTokens(tokens.access_token, tokens.refresh_token);
    return true;
  } catch {
    return false;
  }
};

/**
 * Authenticated fetch with a single 401 refresh-retry. Returns the raw
 * Response (does not throw on HTTP errors — use {@link apiJson} for that).
 */
export const apiRequest = async (
  path: string,
  options: RequestOptions = {},
): Promise<Response> => {
  let response = await send(path, options);
  if (response.status === 401) {
    // The retry re-reads the token from storage, so a successful refresh is
    // picked up automatically. One retry only — a second 401 surfaces.
    if (await refreshOnce()) {
      response = await send(path, options);
    }
  }
  return response;
};

/** Authenticated fetch + JSON parse. Throws {@link ApiError} on non-2xx. */
export const apiJson = async <T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> => {
  const response = await apiRequest(path, options);
  if (response.status === 204) return undefined as unknown as T;
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail =
        typeof body.detail === "string"
          ? body.detail
          : body.detail !== undefined
            ? JSON.stringify(body.detail)
            : detail;
    } catch {
      /* keep status-only detail */
    }
    throw new ApiError(response.status, detail);
  }
  // Some endpoints (e.g. last-messages) return a bare array, others an object.
  return (await response.json()) as T;
};
