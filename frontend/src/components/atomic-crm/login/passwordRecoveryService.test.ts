import { afterEach, describe, expect, it, vi } from "vitest";

import {
  requestPasswordResetOtp,
  resetPasswordWithOtp,
} from "./passwordRecoveryService";

describe("password recovery service", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("requests a reset email with the selected account email", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    globalThis.fetch = fetch as unknown as typeof globalThis.fetch;

    await requestPasswordResetOtp("recruiter@vfic.com.vn");

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/auth/forgot-password"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ email: "recruiter@vfic.com.vn" }),
      }),
    );
  });

  it("surfaces the backend message when a reset request fails", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 429,
      json: async () => ({ detail: "Vui lòng thử lại sau." }),
    }) as unknown as typeof globalThis.fetch;

    await expect(
      requestPasswordResetOtp("recruiter@vfic.com.vn"),
    ).rejects.toThrow("Vui lòng thử lại sau.");
  });

  it("keeps the existing OTP completion payload unchanged", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    globalThis.fetch = fetch as unknown as typeof globalThis.fetch;

    await resetPasswordWithOtp({
      email: "recruiter@vfic.com.vn",
      otp: "123456",
      newPassword: "Secure-password-2026",
    });

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/auth/reset-password"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          email: "recruiter@vfic.com.vn",
          otp: "123456",
          new_password: "Secure-password-2026",
        }),
      }),
    );
  });
});
