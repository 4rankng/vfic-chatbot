// Framework-neutral VFIC REST client + JWT token store.
//
// Replaces the Supabase client. The CRM holds ONLY the user's access/refresh
// JWT pair (never the Zalo OA token or the LLM keys, which stay server-side).
// The access token is attached as a Bearer header on every API call; a 401
// triggers a single transparent refresh attempt (using the stored refresh
// token) before the error surfaces, so a short-lived access token expiring
// mid-session does not log the user out.

import { vficConfig } from "@/lib/runtime-config";

const ACCESS_KEY = "RaStore.auth.access_token";
const REFRESH_KEY = "RaStore.auth.refresh_token";

function storage(): Storage | null {
  if (typeof window !== "undefined" && window.localStorage)
    return window.localStorage;
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
export const apiUrl = (path: string): string =>
  `${vficConfig.apiBaseUrl}${path}`;

/** Error carrying the HTTP status; zero means no server response was received. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Json =
  | Record<string, unknown>
  | unknown[]
  | string
  | number
  | boolean
  | null;

interface RequestOptions {
  method?: string;
  /** JSON body OR a FormData instance (multipart upload — Content-Type auto-set by the browser). */
  body?: Json | FormData;
  /** Extra headers (Authorization is set automatically from the stored token). */
  headers?: Record<string, string>;
  /** Optional AbortSignal for fetch cancellation. */
  signal?: AbortSignal;
}

const isFormData = (body: unknown): body is FormData =>
  typeof FormData !== "undefined" && body instanceof FormData;

let refreshInFlight: Promise<boolean> | null = null;

const jwtSubject = (token: string | null): string | null => {
  if (!token) return null;
  const encodedPayload = token.split(".")[1];
  if (!encodedPayload) return null;
  try {
    const base64 = encodedPayload.replaceAll("-", "+").replaceAll("_", "/");
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
    const payload = JSON.parse(atob(padded)) as { sub?: unknown };
    return typeof payload.sub === "string" && payload.sub
      ? payload.sub
      : null;
  } catch {
    return null;
  }
};

const sharedSessionRotated = (
  attemptedAccessToken: string | null,
  attemptedRefreshToken: string,
): boolean => {
  const currentAccessToken = getAccessToken();
  const currentRefreshToken = getRefreshToken();
  const attemptedSubject = jwtSubject(attemptedAccessToken);
  return (
    attemptedSubject !== null &&
    jwtSubject(currentAccessToken) === attemptedSubject &&
    currentAccessToken !== null &&
    currentRefreshToken !== null &&
    (currentAccessToken !== attemptedAccessToken ||
      currentRefreshToken !== attemptedRefreshToken)
  );
};

const send = async (
  path: string,
  options: RequestOptions,
): Promise<Response> => {
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...options.headers,
  };
  const hasBody = options.body !== undefined;
  const form = isFormData(options.body);
  // FormData: let the browser set Content-Type (incl. the multipart boundary). Never stringify.
  if (hasBody && !form && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  // Marshal the body once so the fetch init type is `string | FormData | undefined`
  // (Json is stringified to a string; FormData passes through untouched).
  let body: BodyInit | undefined;
  if (hasBody) {
    body = form ? (options.body as FormData) : JSON.stringify(options.body);
  }

  try {
    return await fetch(apiUrl(path), {
      method: options.method ?? (hasBody ? "POST" : "GET"),
      headers,
      body,
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof TypeError && !options.signal?.aborted) {
      throw new ApiError(
        0,
        "Không thể kết nối. Kiểm tra mạng rồi thử lại.",
      );
    }
    throw error;
  }
};

const accessTokenRotationListeners = new Set<(accessToken: string) => void>();

/**
 * Subscribe to stored-token rotation (a successful {@link refreshOnce}, including
 * a pair another tab persisted first). Long-lived transports — the realtime
 * socket — capture the token at their handshake and need this to re-authenticate.
 * Returns an unsubscribe function.
 */
export const onAccessTokenRotated = (
  listener: (accessToken: string) => void,
): (() => void) => {
  accessTokenRotationListeners.add(listener);
  return () => {
    accessTokenRotationListeners.delete(listener);
  };
};

const notifyAccessTokenRotated = (): void => {
  const accessToken = getAccessToken();
  if (!accessToken) return;
  for (const listener of [...accessTokenRotationListeners]) {
    try {
      listener(accessToken);
    } catch (error) {
      // A broken subscriber must never break the refresh ladder (that would log
      // the user out), but silence is worse: a socket that fails to
      // re-authenticate looks exactly like a backend that stopped emitting.
      console.error("Access token rotation listener failed", error);
    }
  }
};

// A refresh that succeeds only because another tab rotated the pair still means
// this tab's live connections hold a stale token, so it notifies as well.
const settleRotation = (
  accessToken: string | null,
  refreshToken: string,
): boolean => {
  const rotated = sharedSessionRotated(accessToken, refreshToken);
  if (rotated) notifyAccessTokenRotated();
  return rotated;
};

const runRefresh = async (): Promise<boolean> => {
  const accessToken = getAccessToken();
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;
  try {
    const response = await fetch(apiUrl("/api/v1/auth/refresh"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!response.ok) {
      return settleRotation(accessToken, refreshToken);
    }
    const tokens = (await response.json()) as {
      access_token: string;
      refresh_token: string;
    };
    if (getRefreshToken() !== refreshToken) {
      return settleRotation(accessToken, refreshToken);
    }
    setTokens(tokens.access_token, tokens.refresh_token);
    notifyAccessTokenRotated();
    return true;
  } catch {
    return settleRotation(accessToken, refreshToken);
  }
};

// Exchange the stored refresh token for a fresh access/refresh pair. Concurrent
// 401s in one tab share a single request. Across tabs, localStorage is the
// coordination boundary: a failed/stale refresh accepts a token pair another
// tab already rotated only when both access JWTs identify the same subject.
// Logout, malformed tokens, and an account change all fail closed.
export const refreshOnce = async (): Promise<boolean> => {
  if (refreshInFlight) return refreshInFlight;
  const operation = runRefresh();
  refreshInFlight = operation;
  try {
    return await operation;
  } finally {
    if (refreshInFlight === operation) {
      refreshInFlight = null;
    }
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

/**
 * Map a non-2xx response to a short Vietnamese message. A server-provided
 * plain-string detail wins (it is already a human message); the FastAPI 422
 * validation array and other structured errors collapse to a status-based
 * string so raw English like `[{"type":"less_than_equal",...}]` never reaches
 * a toast. The numeric status is preserved on {@link ApiError} for callers
 * (e.g. humanReplyService) that branch on it.
 */
const friendlyApiMessage = (status: number, rawDetail: unknown): string => {
  if (typeof rawDetail === "string" && rawDetail.trim()) return rawDetail;
  switch (status) {
    case 400:
      return "Yêu cầu không hợp lệ, vui lòng kiểm tra lại.";
    case 401:
      return "Phiên đăng nhập hết hạn, vui lòng đăng nhập lại.";
    case 403:
      return "Bạn không có quyền thực hiện hành động này.";
    case 404:
      return "Không tìm thấy dữ liệu.";
    case 405:
      return "Thao tác này chưa được hỗ trợ.";
    case 409:
      return "Dữ liệu đã tồn tại hoặc xung đột, vui lòng làm mới và thử lại.";
    case 422:
      return "Dữ liệu không hợp lệ, vui lòng kiểm tra lại.";
    case 429:
      return "Thao tác quá nhanh, vui lòng thử lại sau.";
    default:
      return status >= 500
        ? "Lỗi máy chủ, vui lòng thử lại sau."
        : `Yêu cầu thất bại (mã ${status}), vui lòng thử lại.`;
  }
};

/** Authenticated fetch + JSON parse. Throws {@link ApiError} on non-2xx. */
export const apiJson = async <T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> => {
  const response = await apiRequest(path, options);
  if (response.status === 204) return undefined as unknown as T;
  if (!response.ok) {
    let rawDetail: unknown;
    try {
      rawDetail = ((await response.json()) as { detail?: unknown }).detail;
    } catch {
      /* response had no JSON body — fall back to a status-based message */
    }
    throw new ApiError(
      response.status,
      friendlyApiMessage(response.status, rawDetail),
    );
  }
  // Some endpoints (e.g. last-messages) return a bare array, others an object.
  return (await response.json()) as T;
};
