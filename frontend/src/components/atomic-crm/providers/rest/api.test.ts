import { afterEach, describe, expect, it, vi } from "vitest";

import { apiJson, ApiError } from "./api";

/**
 * Regression coverage for the H1 fix: a FastAPI 422 returns a Pydantic
 * validation array as `detail` (e.g. `[{"type":"less_than_equal",...}]`). That
 * array must collapse to a short Vietnamese sentence and never reach a toast
 * verbatim. The numeric status is preserved on ApiError for status-based
 * callers (e.g. humanReplyService).
 *
 * These tests drive the public apiJson entry point with a stubbed global fetch
 * so they exercise the real status->message mapping without importing the
 * (non-exported) mapper directly.
 */
describe("apiJson error mapping", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  const stub = (status: number, body: unknown): typeof globalThis.fetch =>
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    } as unknown as Response) as unknown as typeof globalThis.fetch;

  const expectApiError = async (
    path: string,
    status: number,
  ): Promise<ApiError> => {
    try {
      await apiJson(path);
      throw new Error("expected apiJson to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(status);
      return err as ApiError;
    }
  };

  it("maps a 422 Pydantic validation array to a Vietnamese message (no raw leak)", async () => {
    globalThis.fetch = stub(422, {
      detail: [{ type: "less_than_equal", input: "500" }],
    });
    const err = await expectApiError("/api/v1/leads?per_page=500", 422);
    expect(err.message).toBe("Dữ liệu không hợp lệ, vui lòng kiểm tra lại.");
    // The raw English rule + input must never surface.
    expect(err.message).not.toMatch(/less_than_equal|input/i);
  });

  it("maps a 5xx without a detail body to a server-error message", async () => {
    globalThis.fetch = stub(503, {});
    const err = await expectApiError("/api/v1/dashboard/metrics", 503);
    expect(err.message).toBe("Lỗi máy chủ, vui lòng thử lại sau.");
  });

  it("maps a 401 (no refresh token) to a session-expired message", async () => {
    // No refresh token in storage -> refreshOnce short-circuits, so a single
    // fetch call is made.
    globalThis.fetch = stub(401, {});
    const err = await expectApiError("/api/v1/leads", 401);
    expect(err.message).toBe("Phiên đăng nhập hết hạn, vui lòng đăng nhập lại.");
  });

  it("preserves the numeric status so callers can branch on it", async () => {
    globalThis.fetch = stub(409, { detail: [{ code: "duplicate" }] });
    const err = await expectApiError("/api/v1/users", 409);
    expect(err.status).toBe(409);
    expect(err.name).toBe("ApiError");
  });
});
