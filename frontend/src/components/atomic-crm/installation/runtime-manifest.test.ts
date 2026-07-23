import { afterEach, describe, expect, it, vi } from "vitest";

const { mockApiUrl } = vi.hoisted(() => ({
  mockApiUrl: vi.fn(
    (path: string) => `https://installation-api.example.test${path}`,
  ),
}));

vi.mock("../providers/rest/api", () => ({ apiUrl: mockApiUrl }));

import { fetchRuntimeManifest, parseRuntimeManifest } from "./runtime-manifest";
import { loadRuntimeManifest } from "./runtime-manifest-application";

const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);
const ACTIVE_REVISION_ID = "00000000-0000-4000-8000-000000000009";

const unconfiguredManifest = () => ({
  schema_version: 1,
  lifecycle: "UNCONFIGURED",
  authority_generation: 0,
  revision_id: null,
  pack_key: null,
  pack_version: null,
  pack_contract_hash: null,
  manifest_checksum: null,
  customer_identity: null,
  branding: null,
  locale: null,
  timezone: null,
  currency: null,
  terminology: null,
  capability_ids: [],
  readiness_code: "SETUP_REQUIRED",
  legacy_workspace: false,
});

const activeManifest = () => ({
  schema_version: 1,
  lifecycle: "ACTIVE",
  authority_generation: 9,
  revision_id: ACTIVE_REVISION_ID,
  pack_key: "recruitment",
  pack_version: "1.0.0",
  pack_contract_hash: SHA_A,
  manifest_checksum: SHA_B,
  customer_identity: { display_name: "Configured customer" },
  branding: { app_name: "Configured workspace", primary_color: "#115e59" },
  locale: "vi-VN",
  timezone: "Asia/Ho_Chi_Minh",
  currency: "VND",
  terminology: { lead: "Ung vien" },
  capability_ids: ["conversation", "candidate_intake"],
  readiness_code: "READY",
  legacy_workspace: false,
});

const jsonResponse = (body: unknown, headers?: HeadersInit) => {
  const responseHeaders = new Headers(headers);
  responseHeaders.set("Content-Type", "application/json");
  return new Response(JSON.stringify(body), { status: 200, headers: responseHeaders });
};

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.useRealTimers();
  mockApiUrl.mockClear();
  vi.restoreAllMocks();
});

describe("parseRuntimeManifest", () => {
  it("accepts the exact schema-version-1 UNCONFIGURED projection", () => {
    const payload = unconfiguredManifest();

    expect(parseRuntimeManifest(payload)).toEqual(payload);
  });

  it("recognizes only a pre-setup manifest explicitly marked as a legacy workspace", async () => {
    const { isLegacyWorkspaceRuntime } = await import("./runtime-manifest");

    expect(isLegacyWorkspaceRuntime(parseRuntimeManifest({ ...unconfiguredManifest(), legacy_workspace: true }))).toBe(true);
    expect(isLegacyWorkspaceRuntime(parseRuntimeManifest(unconfiguredManifest()))).toBe(false);
  });

  it("accepts an ACTIVE projection with complete authority evidence", () => {
    const payload = activeManifest();

    expect(parseRuntimeManifest(payload)).toEqual(payload);
  });

  it("treats null optional identity and branding fields as unset", () => {
    const manifest = parseRuntimeManifest({
      ...activeManifest(),
      customer_identity: {
        display_name: "Configured customer",
        legal_name: null,
        support_name: null,
        support_email: null,
        support_phone: null,
        website_url: null,
        address: null,
      },
      branding: { app_name: null, primary_color: null, secondary_color: null },
    });

    expect(manifest.customer_identity?.display_name).toBe("Configured customer");
    expect(manifest.customer_identity?.legal_name).toBeUndefined();
    expect(manifest.customer_identity?.support_email).toBeUndefined();
    expect(manifest.branding?.app_name).toBeUndefined();
    expect(manifest.branding?.primary_color).toBeUndefined();
    expect(manifest.branding?.secondary_color).toBeUndefined();
  });

  it.each([
    ["SUSPENDED", "SUSPENDED"],
    ["UPGRADE_REQUIRED", "UPGRADE_REQUIRED"],
  ])("accepts %s only with complete authority evidence", (lifecycle, readiness) => {
    const payload = {
      ...activeManifest(),
      lifecycle,
      readiness_code: readiness,
    };

    expect(parseRuntimeManifest(payload)).toEqual(payload);
  });

  it.each([
    ["provider_policy", { chat_model: "private-model" }],
    ["persona_body", "private persona instructions"],
    ["integration_requirements", [{ key: "private-integration" }]],
  ])("rejects an extra or unsafe %s field", (field, value) => {
    expect(() => parseRuntimeManifest({ ...activeManifest(), [field]: value })).toThrow();
  });

  it.each(["logo_url", "favicon_url"])(
    "rejects public branding asset field %s even when it looks like a valid URL",
    (field) => {
      expect(() =>
        parseRuntimeManifest({
          ...activeManifest(),
          branding: {
            ...activeManifest().branding,
            [field]: "https://assets.example.test/customer.png",
          },
        }),
      ).toThrow();
    },
  );

  it.each([
    ["unknown schema", { ...unconfiguredManifest(), schema_version: 2 }],
    ["string schema", { ...unconfiguredManifest(), schema_version: "1" }],
    ["unknown lifecycle", { ...unconfiguredManifest(), lifecycle: "READY" }],
  ])("rejects %s", (_label, payload) => {
    expect(() => parseRuntimeManifest(payload)).toThrow();
  });

  it.each(["manifest_checksum", "pack_contract_hash"])(
    "rejects a malformed ACTIVE %s",
    (field) => {
      expect(() =>
        parseRuntimeManifest({ ...activeManifest(), [field]: "not-a-sha256" }),
      ).toThrow();
    },
  );

  it.each([
    "revision_id",
    "pack_key",
    "pack_version",
    "pack_contract_hash",
    "manifest_checksum",
  ])("rejects ACTIVE when authority field %s is missing", (field) => {
    const payload: Record<string, unknown> = activeManifest();
    delete payload[field];

    expect(() => parseRuntimeManifest(payload)).toThrow();
  });

  it.each(["SUSPENDED", "UPGRADE_REQUIRED"])(
    "rejects %s without complete authority evidence",
    (lifecycle) => {
      expect(() =>
        parseRuntimeManifest({
          ...activeManifest(),
          lifecycle,
          readiness_code: lifecycle,
          manifest_checksum: null,
        }),
      ).toThrow();
    },
  );

  it.each([
    ["UNCONFIGURED", "VALIDATION_REQUIRED"],
    ["DRAFT", "RUNTIME_NOT_READY"],
    ["VALIDATED", "SUSPENDED"],
    ["ACTIVE", "SETUP_REQUIRED"],
    ["ACTIVE", "SUSPENDED"],
    ["SUSPENDED", "READY"],
    ["SUSPENDED", "UPGRADE_REQUIRED"],
    ["UPGRADE_REQUIRED", "SUSPENDED"],
  ])("rejects inconsistent %s/%s lifecycle readiness", (lifecycle, readiness) => {
    const authority = ["ACTIVE", "SUSPENDED", "UPGRADE_REQUIRED"].includes(lifecycle)
      ? activeManifest()
      : unconfiguredManifest();

    expect(() =>
      parseRuntimeManifest({
        ...authority,
        lifecycle,
        readiness_code: readiness,
      }),
    ).toThrow();
  });
});

describe("fetchRuntimeManifest", () => {
  it("uses the exact unauthenticated no-store endpoint and accepts a no-store response", async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit): Promise<Response> =>
        jsonResponse(activeManifest(), { "Cache-Control": "no-store" }),
    );
    globalThis.fetch = fetchMock as typeof globalThis.fetch;

    await expect(fetchRuntimeManifest()).resolves.toEqual(activeManifest());

    expect(fetchMock).toHaveBeenCalledOnce();
    const [input, init] = fetchMock.mock.calls[0];
    expect(mockApiUrl).toHaveBeenCalledOnce();
    expect(mockApiUrl).toHaveBeenCalledWith("/api/v1/installation/runtime");
    expect(input).toBe(
      "https://installation-api.example.test/api/v1/installation/runtime",
    );
    expect(init).toMatchObject({
      method: "GET",
      cache: "no-store",
      credentials: "same-origin",
    });
    expect(new Headers(init?.headers).get("Accept")).toBe("application/json");
    expect(new Headers(init?.headers).has("Authorization")).toBe(false);
    expect(init?.signal).toBeInstanceOf(AbortSignal);
  });

  it("aborts a runtime request after the configured timeout", async () => {
    vi.useFakeTimers();
    let requestSignal: AbortSignal | undefined;
    const fetchMock = vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        requestSignal = init?.signal ?? undefined;
        return new Promise((_resolve, reject) => {
          requestSignal?.addEventListener(
            "abort",
            () => reject(new DOMException("Request aborted", "AbortError")),
            { once: true },
          );
        });
      },
    );
    globalThis.fetch = fetchMock as typeof globalThis.fetch;

    const request = fetchRuntimeManifest({ timeoutMs: 25 });
    expect(requestSignal?.aborted).toBe(false);

    await vi.advanceTimersByTimeAsync(25);

    expect(requestSignal?.aborted).toBe(true);
    await expect(request).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("loadRuntimeManifest", () => {
  it("validates the transport response outside the browser adapter", async () => {
    await expect(
      loadRuntimeManifest({
        readRuntimeManifest: async () => ({
          ok: true,
          status: 200,
          cacheControl: "no-store",
          json: async () => activeManifest(),
        }),
      }),
    ).resolves.toEqual(activeManifest());
  });
});
