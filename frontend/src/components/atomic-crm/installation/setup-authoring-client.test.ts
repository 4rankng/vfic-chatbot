import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createSetupPersona,
  getSetupPersonaTemplate,
  type DisabledSetupFollowupRules,
} from "./setup-authoring-client";

const jsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

describe("setup authoring client", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("sends the explicitly disabled proactive follow-up rules when creating a persona", async () => {
    let url = "";
    let request: RequestInit | undefined;
    globalThis.fetch = vi.fn(async (input, init) => {
      url = String(input);
      request = init;
      return jsonResponse({
        id: "00000000-0000-4000-8000-000000000001",
        name: "Agent do quản trị viên tạo",
      });
    }) as typeof globalThis.fetch;
    const followupRules: DisabledSetupFollowupRules = {
      hot: { enabled: false, cadence_hours: [], eligible_stages: [] },
      warm: { enabled: false, cadence_hours: [], eligible_stages: [] },
      not_interested: { enabled: false, cadence_hours: [], eligible_stages: [] },
    };

    await createSetupPersona({
      name: "Agent do quản trị viên tạo",
      body_md: "Nội dung do quản trị viên nhập",
      notes: null,
      followup_rules: followupRules,
    });

    expect(url).toMatch(/\/api\/v1\/knowledge\/personas$/);
    expect(request?.method).toBe("POST");
    expect(JSON.parse(String(request?.body))).toEqual({
      name: "Agent do quản trị viên tạo",
      body_md: "Nội dung do quản trị viên nhập",
      notes: null,
      followup_rules: followupRules,
    });
  });

  it("loads the editable persona format from the existing admin endpoint", async () => {
    let url = "";
    globalThis.fetch = vi.fn(async (input) => {
      url = String(input);
      return new Response("### 1. Vai trò của tôi", {
        headers: { "Content-Type": "text/markdown" },
      });
    }) as typeof globalThis.fetch;

    await expect(getSetupPersonaTemplate()).resolves.toBe("### 1. Vai trò của tôi");
    expect(url).toMatch(/\/api\/v1\/knowledge\/personas\/format\/template$/);
  });
});
