// Logic + state tests for the resend-OTP cooldown hook.
//
// The hook owns three concerns that must be verified independently:
//   1. The 60s countdown drives `cooldownLeft` to 0 and flips `canResend`.
//   2. A successful resend re-arms the cooldown and fires a success toast.
//   3. A 429 re-arms the cooldown (button stays locked); any other error does
//      not (so a transient network blip can be retried at once).
//
// Follows the project convention established by `useConversationRealtime.test`:
// `renderHook` from `vitest-browser-react` + `vi.mock` for the service, with
// fake timers driving the countdown deterministically.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook } from "vitest-browser-react";

import { ApiError } from "@/lib/apiClient";

const { mockRequestPasswordResetOtp } = vi.hoisted(() => ({
  mockRequestPasswordResetOtp: vi.fn(),
}));

vi.mock("./passwordRecoveryService", () => ({
  requestPasswordResetOtp: mockRequestPasswordResetOtp,
}));

import {
  RESEND_COOLDOWN_SECONDS,
  useResendCooldown,
} from "./useResendCooldown";

afterEach(async () => {
  await cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

beforeEach(() => {
  vi.useFakeTimers();
});

describe("useResendCooldown", () => {
  it("starts enabled with no cooldown", async () => {
    const hook = await renderHook(() =>
      useResendCooldown(vi.fn()),
    );
    await hook.act(async () => {
      /* let effects settle */
    });

    expect(hook.result.current.cooldownLeft).toBe(0);
    expect(hook.result.current.isResending).toBe(false);
    expect(hook.result.current.canResend).toBe(true);
  });

  it("re-requests the OTP for the stored email, fires a success toast, and arms the cooldown", async () => {
    const notify = vi.fn();
    mockRequestPasswordResetOtp.mockResolvedValueOnce(undefined);

    const hook = await renderHook(() => useResendCooldown(notify));
    await hook.act(async () => {
      await hook.result.current.resend("recruiter@vfic.com.vn");
    });

    expect(mockRequestPasswordResetOtp).toHaveBeenCalledWith(
      "recruiter@vfic.com.vn",
    );
    expect(mockRequestPasswordResetOtp).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith(
      "Đã gửi lại mã OTP. Vui lòng kiểm tra email.",
      { type: "success" },
    );
    expect(hook.result.current.cooldownLeft).toBe(RESEND_COOLDOWN_SECONDS);
    expect(hook.result.current.canResend).toBe(false);
  });

  it("expires the cooldown after RESEND_COOLDOWN_SECONDS and re-enables resend", async () => {
    const notify = vi.fn();
    mockRequestPasswordResetOtp.mockResolvedValue(undefined);

    const hook = await renderHook(() => useResendCooldown(notify));
    await hook.act(async () => {
      await hook.result.current.resend("a@b.com");
    });
    expect(hook.result.current.cooldownLeft).toBe(RESEND_COOLDOWN_SECONDS);

    // Advance the full window; the interval ticks once per second.
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(RESEND_COOLDOWN_SECONDS * 1000);
    });

    expect(hook.result.current.cooldownLeft).toBe(0);
    expect(hook.result.current.canResend).toBe(true);
  });

  it("re-arms the cooldown on a 429 so the user cannot hammer the endpoint", async () => {
    const notify = vi.fn();
    mockRequestPasswordResetOtp.mockRejectedValueOnce(
      new ApiError(429, "Bạn đã thử quá nhiều lần. Vui lòng thử lại sau vài phút."),
    );

    const hook = await renderHook(() => useResendCooldown(notify));
    await hook.act(async () => {
      await hook.result.current.resend("a@b.com");
    });

    expect(notify).toHaveBeenCalledWith(
      "Bạn đã thử quá nhiều lần. Vui lòng thử lại sau vài phút.",
      { type: "error" },
    );
    expect(hook.result.current.cooldownLeft).toBe(RESEND_COOLDOWN_SECONDS);
    expect(hook.result.current.canResend).toBe(false);
  });

  it("leaves the button enabled after a non-429 error so a transient blip can be retried", async () => {
    const notify = vi.fn();
    mockRequestPasswordResetOtp.mockRejectedValueOnce(
      new ApiError(500, "Lỗi máy chủ, vui lòng thử lại sau."),
    );

    const hook = await renderHook(() => useResendCooldown(notify));
    await hook.act(async () => {
      await hook.result.current.resend("a@b.com");
    });

    expect(notify).toHaveBeenCalledWith("Lỗi máy chủ, vui lòng thử lại sau.", {
      type: "error",
    });
    expect(hook.result.current.cooldownLeft).toBe(0);
    expect(hook.result.current.canResend).toBe(true);
  });

  it("guards against duplicate in-flight resend calls", async () => {
    const notify = vi.fn();
    // Never resolves during the test — keeps the first call in-flight.
    mockRequestPasswordResetOtp.mockReturnValueOnce(new Promise(() => {}));

    const hook = await renderHook(() => useResendCooldown(notify));
    await hook.act(async () => {
      // Fire two resends without awaiting the first.
      void hook.result.current.resend("a@b.com");
      void hook.result.current.resend("a@b.com");
      // Let the microtask queue drain so the first call reaches the await.
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(mockRequestPasswordResetOtp).toHaveBeenCalledTimes(1);
  });

  it("refuses to send for an empty email (defensive guard, no network call)", async () => {
    const notify = vi.fn();
    const hook = await renderHook(() => useResendCooldown(notify));

    await hook.act(async () => {
      await hook.result.current.resend("");
    });

    expect(mockRequestPasswordResetOtp).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalled();
    expect(hook.result.current.cooldownLeft).toBe(0);
  });

  it("startCooldown arms the full window immediately without an HTTP call", async () => {
    const notify = vi.fn();
    const hook = await renderHook(() => useResendCooldown(notify));

    await hook.act(async () => {
      hook.result.current.startCooldown();
    });

    expect(hook.result.current.cooldownLeft).toBe(RESEND_COOLDOWN_SECONDS);
    expect(hook.result.current.canResend).toBe(false);
    expect(mockRequestPasswordResetOtp).not.toHaveBeenCalled();
  });
});
