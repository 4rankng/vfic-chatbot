import { afterEach, describe, expect, it, vi } from "vitest";

import { apiJson, clearTokens, getAccessToken, setTokens } from "./apiClient";

const accessTokenFor = (subject: string, generation: string): string =>
  `header.${btoa(JSON.stringify({ sub: subject, generation }))}.signature`;

/**
 * Coverage for the single 401->refresh->retry ladder in apiRequest. This is the
 * most security/UX-critical path in the REST client (a short-lived access token
 * expiring mid-session must NOT log the user out), and it had zero tests.
 *
 * fetch is stubbed so the sequence is deterministic: the guarded request 401s
 * once, the refresh endpoint returns a fresh pair, and the retry succeeds with
 * the new access token (now persisted).
 */
describe("apiJson 401 refresh-retry", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    clearTokens();
    vi.restoreAllMocks();
  });

  it("refreshes once on 401, retries with the new token, and persists it", async () => {
    setTokens("expired-access", "good-refresh");
    const calls: string[] = [];
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit,
    ): Promise<Response> => {
      const url = typeof input === "string" ? input : input.toString();
      const headers = (init?.headers ?? {}) as Record<string, string>;
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.includes("/auth/refresh")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            access_token: "fresh-access",
            refresh_token: "fresh-refresh",
          }),
        } as unknown as Response;
      }
      // The original request 401s while the stale token is attached, then 200s
      // once the retry carries the refreshed token.
      if (headers.Authorization?.includes("expired-access")) {
        return {
          ok: false,
          status: 401,
          json: async () => ({}),
        } as unknown as Response;
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ hello: "world" }),
      } as unknown as Response;
    }) as unknown as typeof globalThis.fetch;

    const result = await apiJson<{ hello: string }>("/api/v1/leads");

    expect(result).toEqual({ hello: "world" });
    // 3 fetches: original (401) -> refresh -> retry (200). Exactly one retry.
    expect(calls).toHaveLength(3);
    expect(calls[1]).toMatch(/\/auth\/refresh$/);
    expect(getAccessToken()).toBe("fresh-access");
  });

  it("does not retry when there is no refresh token (surfaces the 401)", async () => {
    clearTokens();
    let count = 0;
    globalThis.fetch = (async (): Promise<Response> => {
      count += 1;
      return {
        ok: false,
        status: 401,
        json: async () => ({}),
      } as unknown as Response;
    }) as unknown as typeof globalThis.fetch;

    await expect(apiJson("/api/v1/leads")).rejects.toThrow();
    expect(count).toBe(1);
  });

  it("surfaces the original error when the refresh itself fails", async () => {
    setTokens("expired-access", "bad-refresh");
    let count = 0;
    globalThis.fetch = (async (input: RequestInfo | URL): Promise<Response> => {
      count += 1;
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/auth/refresh")) {
        return {
          ok: false,
          status: 401,
          json: async () => ({}),
        } as unknown as Response;
      }
      return {
        ok: false,
        status: 401,
        json: async () => ({}),
      } as unknown as Response;
    }) as unknown as typeof globalThis.fetch;

    await expect(apiJson("/api/v1/leads")).rejects.toThrow();
    // original (401) -> refresh (401, fails) -> no retry. 2 calls total.
    expect(count).toBe(2);
  });

  it("retries with a token pair rotated by another browser tab", async () => {
    const expiredAccess = accessTokenFor("admin-1", "expired");
    const otherTabAccess = accessTokenFor("admin-1", "fresh");
    setTokens(expiredAccess, "shared-refresh");
    let refreshCalls = 0;
    let protectedCalls = 0;
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit,
    ): Promise<Response> => {
      const url = typeof input === "string" ? input : input.toString();
      const headers = new Headers(init?.headers);
      if (url.includes("/auth/refresh")) {
        refreshCalls += 1;
        // A different tab completes rotation while this tab's request is in
        // flight. Its refresh then fails because the shared token was consumed.
        setTokens(otherTabAccess, "other-tab-refresh");
        return {
          ok: false,
          status: 401,
          json: async () => ({}),
        } as unknown as Response;
      }
      protectedCalls += 1;
      if (headers.get("Authorization") === `Bearer ${expiredAccess}`) {
        return {
          ok: false,
          status: 401,
          json: async () => ({}),
        } as unknown as Response;
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true }),
      } as unknown as Response;
    }) as unknown as typeof globalThis.fetch;

    await expect(
      apiJson<{ ok: boolean }>("/api/v1/leads"),
    ).resolves.toEqual({ ok: true });
    expect(refreshCalls).toBe(1);
    expect(protectedCalls).toBe(2);
    expect(getAccessToken()).toBe(otherTabAccess);
  });

  it.each(["GET", "POST"])(
    "does not replay a %s request after another tab changes accounts",
    async (method) => {
      const firstAccountAccess = accessTokenFor("admin-1", "expired");
      const secondAccountAccess = accessTokenFor("admin-2", "fresh");
      setTokens(firstAccountAccess, "first-account-refresh");
      let refreshCalls = 0;
      let protectedCalls = 0;
      globalThis.fetch = (async (
        input: RequestInfo | URL,
      ): Promise<Response> => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.includes("/auth/refresh")) {
          refreshCalls += 1;
          setTokens(secondAccountAccess, "second-account-refresh");
        } else {
          protectedCalls += 1;
        }
        return {
          ok: false,
          status: 401,
          json: async () => ({}),
        } as unknown as Response;
      }) as unknown as typeof globalThis.fetch;

      await expect(apiJson("/api/v1/leads", { method })).rejects.toThrow();
      expect(refreshCalls).toBe(1);
      expect(protectedCalls).toBe(1);
      expect(getAccessToken()).toBe(secondAccountAccess);
    },
  );

  it("coalesces concurrent 401 refresh attempts into a single refresh request", async () => {
    setTokens("expired-access", "good-refresh");
    let refreshCalls = 0;
    let protectedCalls = 0;
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit,
    ): Promise<Response> => {
      const url = typeof input === "string" ? input : input.toString();
      const headers = new Headers(init?.headers);
      if (url.includes("/auth/refresh")) {
        refreshCalls += 1;
        await Promise.resolve();
        return {
          ok: true,
          status: 200,
          json: async () => ({
            access_token: "fresh-access",
            refresh_token: "fresh-refresh",
          }),
        } as unknown as Response;
      }
      protectedCalls += 1;
      if (headers.get("Authorization")?.includes("expired-access")) {
        return {
          ok: false,
          status: 401,
          json: async () => ({}),
        } as unknown as Response;
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true }),
      } as unknown as Response;
    }) as unknown as typeof globalThis.fetch;

    const [first, second] = await Promise.all([
      apiJson<{ ok: boolean }>("/api/v1/leads"),
      apiJson<{ ok: boolean }>("/api/v1/conversations"),
    ]);

    expect(first).toEqual({ ok: true });
    expect(second).toEqual({ ok: true });
    expect(refreshCalls).toBe(1);
    expect(protectedCalls).toBe(4);
    expect(getAccessToken()).toBe("fresh-access");
  });
});
