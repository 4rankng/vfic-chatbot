import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  clearTokens: vi.fn(),
  closeRealtimeSocket: vi.fn(),
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

describe("authProvider terminal auth errors", () => {
  it("clears local state on a terminal 401 but leaves 403 to the caller", async () => {
    const provider = getAuthProvider();

    await expect(
      provider.checkError?.(new ApiError(401, "expired")),
    ).rejects.toMatchObject({ status: 401 });
    expect(mocks.clearTokens).toHaveBeenCalledOnce();

    vi.clearAllMocks();
    await expect(
      provider.checkError?.(new ApiError(403, "forbidden")),
    ).resolves.toBeUndefined();
    expect(mocks.clearTokens).not.toHaveBeenCalled();
  });
});
