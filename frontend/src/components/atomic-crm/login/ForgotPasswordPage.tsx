import { useState, type ComponentProps, type ComponentType } from "react";
import { Form, required, useInput, useNotify } from "ra-core";
import type { SubmitHandler, FieldValues } from "react-hook-form";
import { Link, useNavigate } from "react-router";
import {
  ArrowLeft,
  ArrowRight,
  KeyRound,
  Loader2,
  Lock,
  Mail,
  RotateCcw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Notification } from "@/components/admin/notification";
import {
  requestPasswordResetOtp,
  resetPasswordWithOtp,
} from "./passwordRecoveryService";
import { useResendCooldown } from "./useResendCooldown";
import { useInstallationContext } from "../installation/installation-context";

type Step = "email" | "otp";

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

  return (
    <div className="kb-scope login-paper min-h-svh overflow-hidden text-foreground">
      <main className="mx-auto flex min-h-svh w-full max-w-[620px] items-center justify-center px-5 py-8 sm:px-8">
        <section className="mx-auto flex w-full max-w-[470px] flex-col justify-center">
          <div className="mb-6 space-y-3 text-center sm:mb-8">
            <p className="text-xl font-semibold leading-none tracking-tight text-foreground sm:text-2xl">
              {activeName ?? "Thiết lập hệ thống"}
            </p>
            <div className="space-y-3">
              <h1 className="kb-display text-balance text-display leading-none text-foreground">
                Khôi phục mật khẩu
              </h1>
              <p className="mx-auto max-w-[360px] text-sm leading-6 text-muted-foreground">
                {step === "email"
                  ? "Nhập email tài khoản để nhận mã OTP."
                  : "Nhập mã OTP và mật khẩu mới cho tài khoản của bạn."}
              </p>
            </div>
          </div>

          <div className="rounded-md border border-border bg-card/92 p-4 shadow-xs backdrop-blur sm:p-6">
            {step === "email" ? (
              <Form className="space-y-4" onSubmit={submitEmail}>
                <RecoveryField
                  label="Email"
                  source="email"
                  type="email"
                  autoComplete="email"
                  placeholder="you@example.com"
                  icon={Mail}
                />
                <Button
                  type="submit"
                  className="mt-2 h-12 w-full cursor-pointer rounded-md text-sm font-semibold"
                  disabled={loading}
                >
                  {loading ? <Loader2 className="size-4 animate-spin" /> : null}
                  Gửi mã OTP
                  {!loading ? <ArrowRight className="size-4" /> : null}
                </Button>
              </Form>
            ) : (
              <Form className="space-y-4" onSubmit={submitOtp}>
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
                />
                <RecoveryField
                  label="Mật khẩu mới"
                  source="new_password"
                  type="password"
                  autoComplete="new-password"
                  icon={Lock}
                />
                <RecoveryField
                  label="Xác nhận mật khẩu"
                  source="confirm_password"
                  type="password"
                  autoComplete="new-password"
                  icon={Lock}
                />
                <Button
                  type="submit"
                  className="mt-2 h-12 w-full cursor-pointer rounded-md text-sm font-semibold"
                  disabled={loading}
                >
                  {loading ? <Loader2 className="size-4 animate-spin" /> : null}
                  Đổi mật khẩu
                  {!loading ? <ArrowRight className="size-4" /> : null}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="h-12 w-full rounded-md text-sm font-semibold"
                  disabled={loading || !canResend}
                  onClick={() => resendOtp(email)}
                >
                  {isResending ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <RotateCcw className="size-4" />
                  )}
                  {cooldownLeft > 0
                    ? `Gửi lại mã (${cooldownLeft}s)`
                    : "Gửi lại mã"}
                </Button>
              </Form>
            )}

            <Link
              to="/login"
              className="mt-5 flex items-center justify-center gap-2 text-sm font-semibold text-foreground underline-offset-4 hover:underline"
            >
              <ArrowLeft className="size-4" />
              Quay lại đăng nhập
            </Link>
          </div>

          <p className="mt-6 text-center text-xs text-muted-foreground">
            Khôi phục quyền truy cập an toàn
          </p>
        </section>
      </main>
      <Notification />
    </div>
  );
};

type RecoveryFieldProps = ComponentProps<"input"> & {
  label: string;
  source: string;
  icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
};

const RecoveryField = ({
  label,
  source,
  icon: Icon,
  type = "text",
  defaultValue,
  ...inputProps
}: RecoveryFieldProps) => {
  const { id, field, isRequired } = useInput({
    source,
    type,
    validate: inputProps.disabled ? undefined : required(),
    defaultValue,
  });

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="font-semibold text-muted-foreground">
        {label}
      </Label>
      <div className="relative">
        <Icon
          aria-hidden
          className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          id={id}
          type={type}
          required={isRequired}
          className="h-12 rounded-md bg-background/70 pl-11 text-base shadow-none placeholder:text-muted-foreground/70 disabled:opacity-100"
          {...inputProps}
          {...field}
        />
      </div>
    </div>
  );
};
