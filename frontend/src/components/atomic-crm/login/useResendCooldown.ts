import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/apiClient";
import { requestPasswordResetOtp } from "./passwordRecoveryService";

/** Frontend cooldown between resend clicks. The backend allows 3 requests per
 *  email per 15 minutes, so 60s leaves comfortable headroom and matches user
 *  expectations for "just sent, wait a bit" UX. */
export const RESEND_COOLDOWN_SECONDS = 60;

type NotifyFn = (msg: string, opts?: { type?: "success" | "error" }) => void;

export type ResendState = {
  /** Seconds remaining on the cooldown timer. 0 means the user may resend. */
  cooldownLeft: number;
  /** True while a resend HTTP request is in flight. */
  isResending: boolean;
  /** Convenience flag: the Resend button is enabled iff this is true. */
  canResend: boolean;
  /** Start the 60s countdown. Called after a successful initial send or resend. */
  startCooldown: () => void;
  /** Re-request an OTP for the given email. Guards against double-clicks and
   *  cooldown. Handles 429 by re-arming the cooldown; other errors leave the
   *  button enabled so a transient blip can be retried immediately. */
  resend: (email: string) => Promise<void>;
};

/**
 * Owns the resend-OTP cooldown + HTTP state for {@link ForgotPasswordPage}.
 *
 * Extracted from the component so the timer logic and 429 handling can be unit
 * tested without a DOM testing library (the frontend doesn't ship one).
 *
 * `notify` is passed in (the component's ra-core `useNotify`) and stored in a
 * ref so the `resend` callback's dependency list stays minimal.
 */
export function useResendCooldown(notify: NotifyFn): ResendState {
  const [cooldownLeft, setCooldownLeft] = useState(0);
  const [isResending, setIsResending] = useState(false);
  // Synchronous re-entry guard. `isResending` state is async/batched, so two
  // synchronous `resend()` calls would both observe false and both fire. The
  // ref flips synchronously and is the real guard; the state only drives UI.
  const isResendingRef = useRef(false);
  const notifyRef = useRef(notify);
  notifyRef.current = notify;

  useEffect(() => {
    if (cooldownLeft <= 0) return;
    const id = setInterval(() => {
      setCooldownLeft((prev) => (prev <= 1 ? 0 : prev - 1));
    }, 1000);
    return () => clearInterval(id);
    // Re-subscribe only on edge transitions so the interval stays alive across
    // decrement ticks (the boolean stays true while counting) and tears down
    // exactly once at the 0 edge — avoids re-creating the interval every second.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cooldownLeft > 0]);

  const startCooldown = useCallback(
    () => setCooldownLeft(RESEND_COOLDOWN_SECONDS),
    [],
  );

  const resend = useCallback(
    async (email: string) => {
      if (isResendingRef.current || cooldownLeft > 0) return;
      if (!email) return; // defensive: never send an empty payload
      isResendingRef.current = true;
      setIsResending(true);
      try {
        await requestPasswordResetOtp(email);
        notifyRef.current("Đã gửi lại mã OTP. Vui lòng kiểm tra email.", {
          type: "success",
        });
        startCooldown();
      } catch (e) {
        const err = e as ApiError;
        notifyRef.current(err.message, { type: "error" });
        // On 429 the backend already told the user to wait — re-arm the cooldown
        // so they don't hammer the endpoint. On any other error, leave the
        // button enabled so a transient network blip can be retried at once.
        if (err.status === 429) startCooldown();
      } finally {
        isResendingRef.current = false;
        setIsResending(false);
      }
    },
    [cooldownLeft, startCooldown],
  );

  return {
    cooldownLeft,
    isResending,
    canResend: !isResending && cooldownLeft === 0,
    startCooldown,
    resend,
  };
}
