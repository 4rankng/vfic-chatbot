import { describe, expect, it } from "vitest";

import type { ExternalApiView } from "./external-api-contracts";
import {
  buildExternalApiPayload,
  emptyExternalApiForm,
  EXTERNAL_API_MAX_GUIDE_CHARS,
  formFromView,
  validateExternalApiForm,
} from "./external-api-policy";

const GUIDE = [
  "# Hướng dẫn tích hợp API",
  "POST /api/v1/integration/employee/lookup — tra cứu nhân viên.",
  "POST /api/v1/integration/password-reset/otp — gửi OTP qua Zalo.",
].join("\n");

const view = (overrides: Partial<ExternalApiView> = {}): ExternalApiView => ({
  enabled: true,
  base_url: "https://api.example.com",
  auth_header: "X-API-Key",
  auth_scheme: "",
  guide: GUIDE,
  api_key: { configured: true, preview: "10 ký tự" },
  chatbot_readiness: { ready: true, blockers: [] },
  ...overrides,
});

describe("external api form policy", () => {
  it("always starts the key field blank so a saved secret is preserved", () => {
    const form = formFromView(view());
    expect(form.api_key).toBe("");
    expect(form.clear_api_key).toBe(false);
    expect(form.guide).toBe(GUIDE);
    expect(form.base_url).toBe("https://api.example.com");
  });

  it("omits api_key when the draft field is blank", () => {
    const payload = buildExternalApiPayload(formFromView(view()));
    expect("api_key" in payload).toBe(false);
  });

  it("sends the new key when one is typed", () => {
    const payload = buildExternalApiPayload({
      ...formFromView(view()),
      api_key: "  ttk_fresh  ",
    });
    expect(payload.api_key).toBe("ttk_fresh");
  });

  it("sends an explicit empty key only for the clear action", () => {
    const payload = buildExternalApiPayload({
      ...formFromView(view()),
      clear_api_key: true,
    });
    expect(payload.api_key).toBe("");
  });

  it("keeps the guide verbatim and trims the origin", () => {
    const payload = buildExternalApiPayload({
      ...formFromView(view()),
      base_url: "  https://api.example.com/  ",
    });
    expect(payload.base_url).toBe("https://api.example.com/");
    expect(payload.guide).toBe(GUIDE);
  });

  it("accepts a valid enabled form", () => {
    expect(validateExternalApiForm(formFromView(view()))).toEqual([]);
  });

  it("rejects plain http off loopback", () => {
    expect(
      validateExternalApiForm({
        ...formFromView(view()),
        base_url: "http://api.example.com",
      }),
    ).toContain("Chỉ dùng http cho 127.0.0.1/localhost; còn lại phải là https.");
    expect(
      validateExternalApiForm({
        ...formFromView(view()),
        base_url: "http://127.0.0.1:8799",
      }),
    ).toEqual([]);
  });

  it("rejects a relative base URL", () => {
    expect(
      validateExternalApiForm({
        ...formFromView(view()),
        base_url: "api.example.com",
      }),
    ).toContain(
      "Base URL phải là một địa chỉ tuyệt đối, ví dụ https://api.example.com.",
    );
  });

  it("requires a base URL and a guide when enabled", () => {
    const errors = validateExternalApiForm({
      ...emptyExternalApiForm(),
      enabled: true,
    });
    expect(errors).toContain("Bật tích hợp cần nhập Base URL.");
    expect(errors).toContain("Bật tích hợp cần dán hoặc tải lên hướng dẫn API.");
  });

  it("bounds the guide length", () => {
    expect(
      validateExternalApiForm({
        ...formFromView(view()),
        guide: "x".repeat(EXTERNAL_API_MAX_GUIDE_CHARS + 1),
      }),
    ).toContain(
      `Hướng dẫn API tối đa ${EXTERNAL_API_MAX_GUIDE_CHARS} ký tự (hiện ${
        EXTERNAL_API_MAX_GUIDE_CHARS + 1
      }).`,
    );
  });

  it("allows a disabled form to be empty", () => {
    expect(validateExternalApiForm(emptyExternalApiForm())).toEqual([]);
  });
});
