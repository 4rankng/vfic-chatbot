import { useState, type ComponentType } from "react";
import { Form, required, useInput, useNotify, ValidationError } from "ra-core";
import type { SubmitHandler, FieldValues } from "react-hook-form";
import { Link, useNavigate } from "react-router";
import {
  ArrowLeft,
  ArrowRight,
  KeyRound,
  Lock,
  Mail,
  RotateCcw,
} from "lucide-react";

import { Button } from "@/components/base/buttons/button";
import { InputBase, TextField } from "@/components/base/input/input";
import { Label } from "@/components/base/input/label";
import { HintText } from "@/components/base/input/hint-text";
import { Notification } from "@/components/admin/notification";
import {
  requestPasswordResetOtp,
  resetPasswordWithOtp,
} from "./passwordRecoveryService";
import { useResendCooldown } from "./useResendCooldown";
import { useInstallationContext } from "../installation/installation-context";
import { AuthShell } from "./AuthShell";

type Step = "email" | "otp";

/**
 * The recovery flow renders on the same Untitled UI anatomy as the sign-in form:
 * `TextField` / `Label` / `InputBase` for the fields and `Button` for the three
 * actions.
 *
 * `validationBehavior="aria"` keeps React Aria's default `native` behaviour from
 * writing `required` onto the input, so react-admin's own validator runs and the
 * user sees the console's Vietnamese error instead of a browser bubble.
 * `uu-scope` re-binds the four utility names this console and Untitled UI both
 * define (`bg-primary`, `bg-secondary`, `text-primary`, `border-primary`) — see
 * `src/styles/untitledui-theme.css`.
 *
 * The password fields compose `InputBase` rather than the composed `Input` so no
 * English-labelled reveal eye is introduced: the flow has never offered one.
 */
export const ForgotPasswordPage = () => {
  const { manifest } = useInstallationContext();
  const notify = useNotify();
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const {
    cooldownLeft,
    isResending,
    canResend,
    startCooldown,
    resend: resendOtp,
  } = useResendCooldown(notify);
  const activeName =
    manifest.lifecycle === "ACTIVE"
      ? manifest.branding?.app_name?.trim() ||
        manifest.customer_identity?.display_name.trim()
      : null;

  const submitEmail: SubmitHandler<FieldValues> = async (values) => {
    const nextEmail = String(values.email ?? "")
      .trim()
      .toLowerCase();
    if (!nextEmail) {
      notify("Vui lòng nhập email.", { type: "error" });
      return;
    }
    setLoading(true);
    try {
      await requestPasswordResetOtp(nextEmail);
      setEmail(nextEmail);
      setStep("otp");
      // Arm the resend cooldown so the user can't immediately re-request and
      // burn the backend's 3-requests-per-email-per-15-min budget.
      startCooldown();
      notify("Nếu email hợp lệ, mã OTP đã được gửi.", { type: "success" });
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setLoading(false);
    }
  };

  const submitOtp: SubmitHandler<FieldValues> = async (values) => {
    const otp = String(values.otp ?? "").trim();
    const newPassword = String(values.new_password ?? "");
    const confirmPassword = String(values.confirm_password ?? "");
    if (newPassword !== confirmPassword) {
      notify("Mật khẩu xác nhận không khớp.", { type: "error" });
      return;
    }
    setLoading(true);
    try {
      await resetPasswordWithOtp({ email, otp, newPassword });
      notify("Đã đổi mật khẩu. Vui lòng đăng nhập lại.", { type: "success" });
      navigate("/login");
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setLoading(false);
    }
  };

  const productName = activeName ?? "TingHire";

  return (
    <>
      <AuthShell productName={productName}>
        <section className="flex w-full flex-col justify-center">
          <div className="mb-6 space-y-3 text-center sm:mb-8">
            <div className="space-y-3">
              <h1 className="kb-display text-balance text-page-title leading-none text-foreground">
                Khôi phục mật khẩu
              </h1>
              <p className="mx-auto max-w-[360px] text-body leading-6 text-muted-foreground">
                {step === "email"
                  ? "Nhập email tài khoản để nhận mã OTP."
                  : "Nhập mã OTP và mật khẩu mới cho tài khoản của bạn."}
              </p>
            </div>
          </div>

          <div className="uu-scope tt-card rounded-xl border border-base-300 bg-base-100 p-4 shadow-sm sm:p-6">
            {step === "email" ? (
              <Form className="space-y-4" onSubmit={submitEmail} noValidate>
                <RecoveryField
                  label="Email"
                  source="email"
                  type="email"
                  autoComplete="email"
                  placeholder="you@example.com"
                  icon={Mail}
                  disabled={loading}
                  validateRequired
                />
                <Button
                  type="submit"
                  size="lg"
                  className="mt-2 h-12 w-full"
                  isDisabled={loading}
                  isLoading={loading}
                  showTextWhileLoading
                  iconTrailing={loading ? undefined : ArrowRight}
                >
                  Gửi mã OTP
                </Button>
              </Form>
            ) : (
              <Form className="space-y-4" onSubmit={submitOtp} noValidate>
                <RecoveryField
                  label="Email"
                  source="email"
                  type="email"
                  defaultValue={email}
                  disabled
                  icon={Mail}
                />
                <RecoveryField
                  label="Mã OTP"
                  source="otp"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="000000"
                  icon={KeyRound}
                  disabled={loading}
                  validateRequired
                />
                <RecoveryField
                  label="Mật khẩu mới"
                  source="new_password"
                  type="password"
                  autoComplete="new-password"
                  icon={Lock}
                  disabled={loading}
                  validateRequired
                />
                <RecoveryField
                  label="Xác nhận mật khẩu"
                  source="confirm_password"
                  type="password"
                  autoComplete="new-password"
                  icon={Lock}
                  disabled={loading}
                  validateRequired
                />
                <Button
                  type="submit"
                  size="lg"
                  className="mt-2 h-12 w-full"
                  isDisabled={loading}
                  isLoading={loading}
                  showTextWhileLoading
                  iconTrailing={loading ? undefined : ArrowRight}
                >
                  Đổi mật khẩu
                </Button>
                <Button
                  type="button"
                  color="secondary"
                  size="lg"
                  className="h-12 w-full"
                  isDisabled={loading || !canResend}
                  isLoading={isResending}
                  showTextWhileLoading
                  iconLeading={
                    isResending ? undefined : <RotateCcw className="size-4" />
                  }
                  onClick={() => resendOtp(email)}
                >
                  {cooldownLeft > 0
                    ? `Gửi lại mã (${cooldownLeft}s)`
                    : "Gửi lại mã"}
                </Button>
              </Form>
            )}

            <Link
              to="/login"
              className="mt-5 flex items-center justify-center gap-2 text-body font-semibold text-foreground underline-offset-4 hover:underline"
            >
              <ArrowLeft className="size-4" />
              Quay lại đăng nhập
            </Link>
          </div>

          <p className="mt-6 text-center text-helper text-muted-foreground">
            Khôi phục quyền truy cập an toàn
          </p>
        </section>
      </AuthShell>
      <Notification />
    </>
  );
};

type RecoveryFieldProps = {
  label: string;
  source: string;
  type?: "text" | "email" | "password";
  placeholder?: string;
  autoComplete?: string;
  inputMode?: "numeric" | "text";
  defaultValue?: string;
  disabled?: boolean;
  validateRequired?: boolean;
  icon: ComponentType<{ className?: string }>;
};

const RecoveryField = ({
  label,
  source,
  type = "text",
  placeholder,
  autoComplete,
  inputMode,
  defaultValue,
  disabled,
  validateRequired = false,
  icon: Icon,
}: RecoveryFieldProps) => {
  const { id, field, fieldState, isRequired } = useInput({
    source,
    type,
    validate: validateRequired
      ? required(`Vui lòng nhập ${label.toLocaleLowerCase("vi-VN")}.`)
      : undefined,
    defaultValue,
  });

  return (
    <TextField
      id={id}
      className="uu-scope gap-1.5"
      name={field.name}
      type={type}
      value={typeof field.value === "string" ? field.value : ""}
      onChange={(value: string) => field.onChange(value)}
      onBlur={field.onBlur}
      validationBehavior="aria"
      isRequired={isRequired}
      isDisabled={disabled}
      isInvalid={Boolean(fieldState.error)}
    >
      <Label>{label}</Label>
      {/*
        `[&>button]:hidden` suppresses the primitive's password eye. This flow has
        never offered a reveal action, and the primitive's eye is labelled in
        English — the console is Vietnamese-only.
      */}
      <InputBase
        ref={field.ref}
        type={type}
        icon={Icon}
        placeholder={placeholder}
        autoComplete={autoComplete}
        inputMode={inputMode}
        isDisabled={disabled}
        isInvalid={Boolean(fieldState.error)}
        inputClassName="min-h-12"
        wrapperClassName={type === "password" ? "[&>button]:hidden" : undefined}
      />
      {fieldState.error?.message ? (
        <HintText isInvalid role="alert">
          <ValidationError error={fieldState.error.message} />
        </HintText>
      ) : null}
    </TextField>
  );
};
