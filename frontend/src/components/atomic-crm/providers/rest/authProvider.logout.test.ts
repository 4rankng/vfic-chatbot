import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiJson: vi.fn(),
  clearActiveDecisionTraceQueries: vi.fn(),
  clearTokens: vi.fn(),
  closeRealtimeSocket: vi.fn(),
}));

vi.mock("../../root/reset-runtime-state", () => ({
  clearActiveDecisionTraceQueries: mocks.clearActiveDecisionTraceQueries,
}));

vi.mock("../realtime/realtime-socket", () => ({
  closeRealtimeSocket: mocks.closeRealtimeSocket,
}));

vi.mock("@/lib/apiClient", () => {
  class ApiError extends Error {
    constructor(
      public status: number,
      message: string,
    ) {
      super(message);
    }
  }
  return {
    ApiError,
    apiJson: mocks.apiJson,
    clearTokens: mocks.clearTokens,
    getAccessToken: vi.fn(() => null),
    refreshOnce: vi.fn(),
    setTokens: vi.fn(),
  };
});

import { getAuthProvider } from "./authProvider";

const IDENTITY_KEY = "RaStore.auth.identity";

afterEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

/**
 * SEC-03: logout must revoke the session server-side, not just clear
 * localStorage. The old refresh token stayed usable for its full 14-day life
 * after a local-only logout.
 */
describe("authProvider server-side logout", () => {
  it("posts to /auth/logout before clearing local state", async () => {
    window.localStorage.setItem(
      IDENTITY_KEY,
      JSON.stringify({ id: "admin-1", role: "admin" }),
    );
    const order: string[] = [];
    mocks.apiJson.mockImplementation(async (path: string) => {
      order.push(`api:${path}`);
    });
    mocks.clearTokens.mockImplementation(() => order.push("clearTokens"));

    await getAuthProvider().logout?.({});

    expect(mocks.apiJson).toHaveBeenCalledWith("/api/v1/auth/logout", {
      method: "POST",
    });
    expect(order).toEqual(["api:/api/v1/auth/logout", "clearTokens"]);
    expect(window.localStorage.getItem(IDENTITY_KEY)).toBeNull();
    expect(mocks.closeRealtimeSocket).toHaveBeenCalledOnce();
  });

  it("still logs out locally when the server call fails", async () => {
    window.localStorage.setItem(
      IDENTITY_KEY,
      JSON.stringify({ id: "admin-1", role: "admin" }),
    );
    mocks.apiJson.mockRejectedValue(new Error("offline"));

    await expect(getAuthProvider().logout?.({})).resolves.toBeUndefined();

    expect(mocks.clearTokens).toHaveBeenCalledOnce();
    expect(mocks.closeRealtimeSocket).toHaveBeenCalledOnce();
    expect(window.localStorage.getItem(IDENTITY_KEY)).toBeNull();
  });

  it("clears sensitive trace queries before the server call", async () => {
    const order: string[] = [];
    mocks.clearActiveDecisionTraceQueries.mockImplementation(() =>
      order.push("clearTraceQueries"),
    );
    mocks.apiJson.mockImplementation(async () => {
      order.push("logout");
    });

    await getAuthProvider().logout?.({});

    expect(order).toEqual(["clearTraceQueries", "logout"]);
  });
});
