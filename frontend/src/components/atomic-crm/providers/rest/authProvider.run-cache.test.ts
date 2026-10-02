import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  clearActiveBotRunQueries: vi.fn(),
  clearTokens: vi.fn(),
  closeRealtimeSocket: vi.fn(),
}));

vi.mock("../../root/reset-runtime-state", () => ({
  clearActiveBotRunQueries: mocks.clearActiveBotRunQueries,
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
    apiJson: vi.fn(),
    clearTokens: mocks.clearTokens,
    getAccessToken: vi.fn(() => null),
    refreshOnce: vi.fn(),
    setTokens: vi.fn(),
  };
});

import { ApiError } from "@/lib/apiClient";
import { getAuthProvider } from "./authProvider";

afterEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

describe("authProvider cached bot-run privacy", () => {
  it("clears cached bot-run queries before logout completes", async () => {
    window.localStorage.setItem(
      "RaStore.auth.identity",
      JSON.stringify({ id: "admin-1", role: "admin" }),
    );

    await getAuthProvider().logout?.({});

    expect(mocks.clearActiveBotRunQueries).toHaveBeenCalledOnce();
    expect(mocks.clearTokens).toHaveBeenCalledOnce();
    expect(window.localStorage.getItem("RaStore.auth.identity")).toBeNull();
    expect(mocks.closeRealtimeSocket).toHaveBeenCalledOnce();
  });

  it("clears cached bot-run queries after a terminal 401 but not a 403", async () => {
    const provider = getAuthProvider();

    await expect(
      provider.checkError?.(new ApiError(401, "expired")),
    ).rejects.toMatchObject({ status: 401 });
    expect(mocks.clearActiveBotRunQueries).toHaveBeenCalledOnce();

    vi.clearAllMocks();
    await expect(
      provider.checkError?.(new ApiError(403, "forbidden")),
    ).resolves.toBeUndefined();
    expect(mocks.clearActiveBotRunQueries).not.toHaveBeenCalled();
  });
});
