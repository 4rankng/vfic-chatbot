import { afterEach, describe, expect, it, vi } from "vitest";

import * as installationClient from "./installation-client";
import {
  InstallationClientError,
  finalizeInstallationSetupDraft,
  getInstallationCatalog,
  getInstallationSetupDraft,
  saveInstallationSetupDraft,
} from "./installation-client";

const jsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const revisionResponse = () => ({
  id: "00000000-0000-4000-8000-000000000001",
  revision_no: 1,
  predecessor_id: null,
  pack_key: "configured-pack",
  pack_version: "1.0.0",
  pack_contract_hash: "a".repeat(64),
  manifest_checksum: "b".repeat(64),
  customer_identity: { display_name: "Configured customer" },
  branding: { app_name: "Configured app" },
  locale: "vi-VN",
  timezone: "Asia/Ho_Chi_Minh",
  currency: "VND",
  terminology: {},
  workflow_policy: {},
  workflow_policy_checksum: "c".repeat(64),
  capability_ids: [],
  persona_version_id: "00000000-0000-4000-8000-000000000002",
  template_version_refs: [],
  provider_policy: {},
  provider_policy_checksum: "d".repeat(64),
  integration_requirements: [],
  authentication_policy: { email_password_enabled: true },
  authentication_policy_checksum: "e".repeat(64),
  created_by: null,
  created_at: "2026-07-15T00:00:00Z",
});

const draftPayload = {
  identity_branding: {
    customer_identity: { display_name: "Công ty thử nghiệm" },
    branding: { app_name: "Cổng tư vấn" },
  },
};

describe("installation setup client", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("loads the persisted setup draft and code-owned catalog", async () => {
    const calls: string[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push(url);
      if (url.endsWith("/api/v1/admin/installation/catalog")) {
        return jsonResponse({
          schema_version: 1,
          packs: [],
          capabilities: [],
          locales: [],
          currencies: [],
          workflows: [],
          integration_keys: [],
          authentication_methods: ["email_password"],
        });
      }
      return jsonResponse({
        payload: draftPayload,
        lock_version: 4,
        installation_lock_version: 2,
        section_completion: { identity_branding: true },
        issues: [],
      });
    }) as typeof globalThis.fetch;

    const [draft, catalog] = await Promise.all([
      getInstallationSetupDraft(),
      getInstallationCatalog(),
    ]);

    expect(draft.lock_version).toBe(4);
    expect(catalog.schema_version).toBe(1);
    expect(calls.some((url) => url.endsWith("/api/v1/admin/installation/setup-draft"))).toBe(
      true,
    );
    expect(calls.some((url) => url.endsWith("/api/v1/admin/installation/catalog"))).toBe(
      true,
    );
  });

  it("sends the submitted draft with its expected optimistic lock", async () => {
    let request: RequestInit | undefined;
    globalThis.fetch = vi.fn(async (_input, init) => {
      request = init;
      return jsonResponse({
        payload: draftPayload,
        lock_version: 5,
        installation_lock_version: 2,
        section_completion: { identity_branding: true },
        issues: [],
      });
    }) as typeof globalThis.fetch;

    await saveInstallationSetupDraft(draftPayload, 4);

    expect(request?.method).toBe("PUT");
    expect(JSON.parse(String(request?.body))).toEqual({
      payload: draftPayload,
      expected_lock_version: 4,
    });
  });

  it("sends both draft and installation locks when finalizing", async () => {
    let url = "";
    let request: RequestInit | undefined;
    globalThis.fetch = vi.fn(async (input, init) => {
      url = String(input);
      request = init;
      return jsonResponse(revisionResponse(), 201);
    }) as typeof globalThis.fetch;

    await finalizeInstallationSetupDraft({
      expectedDraftLockVersion: 5,
      expectedInstallationLockVersion: 9,
    });

    expect(url).toMatch(/\/api\/v1\/admin\/installation\/setup-draft\/finalize$/);
    expect(request?.method).toBe("POST");
    expect(JSON.parse(String(request?.body))).toEqual({
      expected_draft_lock_version: 5,
      expected_installation_lock_version: 9,
    });
  });

  it("preserves stable conflict details and the unsaved client draft", async () => {
    globalThis.fetch = vi.fn(async () =>
      jsonResponse(
        {
          detail: "Installation changed since it was loaded",
          code: "INSTALLATION_CONFLICT",
          lifecycle: "DRAFT",
          issues: [
            {
              code: "STALE_LOCK_VERSION",
              message: "Reload before saving",
              path: "expected_lock_version",
            },
          ],
        },
        409,
      ),
    ) as typeof globalThis.fetch;

    const rejected = saveInstallationSetupDraft(draftPayload, 4).catch(
      (error: unknown) => error,
    );

    await expect(rejected).resolves.toMatchObject({
      status: 409,
      code: "INSTALLATION_CONFLICT",
      lifecycle: "DRAFT",
      expectedLockVersion: 4,
      submittedDraft: draftPayload,
      issues: [
        {
          code: "STALE_LOCK_VERSION",
          message: "Reload before saving",
          path: "expected_lock_version",
        },
      ],
    });
    await expect(rejected).resolves.toBeInstanceOf(InstallationClientError);
  });

  it("snapshots the submitted draft before caller state can mutate", async () => {
    let completeRequest: ((response: Response) => void) | undefined;
    globalThis.fetch = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          completeRequest = resolve;
        }),
    ) as typeof globalThis.fetch;
    const mutableDraft = structuredClone(draftPayload);

    const rejected = saveInstallationSetupDraft(mutableDraft, 4).catch(
      (error: unknown) => error,
    );
    mutableDraft.identity_branding.customer_identity.display_name =
      "Giá trị đã sửa sau khi gửi";
    completeRequest?.(
      jsonResponse(
        {
          detail: "Installation changed since it was loaded",
          code: "INSTALLATION_CONFLICT",
          lifecycle: "DRAFT",
          issues: [],
        },
        409,
      ),
    );

    await expect(rejected).resolves.toMatchObject({
      submittedDraft: draftPayload,
    });
    const error = (await rejected) as InstallationClientError;
    expect(error.submittedDraft).not.toBe(mutableDraft);
  });

  it("does not expose activation before runtime composition is enforceable", () => {
    expect("activateInstallationRevision" in installationClient).toBe(false);
    expect("activateInstallation" in installationClient).toBe(false);
  });
});
