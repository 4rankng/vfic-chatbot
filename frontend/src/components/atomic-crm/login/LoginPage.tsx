import { useState } from "react";
import {
  Form,
  required,
  useInput,
  useLogin,
  useNotify,
  useTranslate,
} from "ra-core";
import type { SubmitHandler, FieldValues } from "react-hook-form";
import { Link } from "react-router";
import { ArrowRight, Eye, EyeOff, Loader2, Lock, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Notification } from "@/components/admin/notification";
import { useConfigurationContext } from "@/components/atomic-crm/root/ConfigurationContext.tsx";
import { SSOAuthButton } from "./SSOAuthButton";

/**
 * Login page displayed when authentication is enabled and the user is not authenticated.
 *
 * Automatically shown when an unauthenticated user tries to access a protected route.
 * Handles login via authProvider.login() and displays error notifications on failure.
 *
 * Layout follows the Ting Ting operations console: a blue application shell,
 * a cool workspace canvas, and the same crisp panel geometry used after sign-in.
 *
 * @see {@link https://marmelab.com/shadcn-admin-kit/docs/loginpage LoginPage documentation}
 * @see {@link https://marmelab.com/shadcn-admin-kit/docs/security Security documentation}
 */
export const LoginPage = (props: { redirectTo?: string }) => {
  const { googleWorkplaceDomain, disableEmailPasswordAuthentication } =
    useConfigurationContext();
  const { redirectTo } = props;
  const [loading, setLoading] = useState(false);
  const login = useLogin();
  const notify = useNotify();
  const translate = useTranslate();

  const handleSubmit: SubmitHandler<FieldValues> = (values) => {
    setLoading(true);
    login(values, redirectTo)
      .then(() => {
        setLoading(false);
      })
      .catch((error) => {
        setLoading(false);
        notify(
          typeof error === "string"
            ? error
            : typeof error === "undefined" || !error.message
              ? "ra.auth.sign_in_error"
              : error.message,
          {
            type: "error",
            messageArgs: {
              _:
                typeof error === "string"
                  ? error
                  : error && error.message
                    ? error.message
                    : undefined,
            },
          },
        );
      });
  };

  const showEmailPassword = !disableEmailPasswordAuthentication;
  const showSso = Boolean(googleWorkplaceDomain);
  const showDivider = showEmailPassword && showSso;

  return (
    <div className="min-h-svh overflow-hidden bg-[var(--workspace-shell)] text-[var(--workspace-ink)]">
      <main className="grid min-h-svh lg:grid-cols-[minmax(24rem,0.88fr)_minmax(36rem,1.12fr)]">
        <aside
          aria-labelledby="login-brand-title"
          className="relative hidden min-h-svh overflow-hidden bg-[var(--workspace-shell)] lg:block"
        >
          <img
            src="/login-recruiting-workspace.jpg"
            alt=""
            aria-hidden="true"
            decoding="async"
            className="absolute inset-0 h-full w-full object-cover object-[68%_center] opacity-55"
          />
          <div className="absolute inset-0 bg-[linear-gradient(160deg,rgba(57,79,121,0.9)_0%,rgba(80,110,174,0.8)_42%,rgba(80,110,174,0.46)_100%)]" />

          <div className="relative flex min-h-svh flex-col p-10 xl:p-14">
            <div className="flex items-center gap-3 text-white">
              <img
                src="/ttsoft-logo.png"
                alt=""
                aria-hidden="true"
                className="size-11 shrink-0 rounded-full object-contain ring-1 ring-white/45"
              />
              <span className="text-[1.125rem] font-semibold tracking-[-0.02em]">
                Ting Ting Soft
              </span>
            </div>

            <div className="my-auto max-w-md pt-20">
              <p className="mb-5 font-mono text-xs font-semibold tracking-[0.16em] text-white/70">
                TRUNG TÂM TUYỂN DỤNG
              </p>
              <h1
                id="login-brand-title"
                className="max-w-sm text-balance text-4xl font-semibold leading-[1.08] tracking-[-0.04em] text-white xl:text-5xl"
              >
                Giữ từng cuộc trò chuyện ứng viên trong tầm tay.
              </h1>
              <p className="mt-6 max-w-[29rem] text-pretty text-base leading-7 text-white/78">
                Một không gian làm việc rõ ràng để đội ngũ tuyển dụng theo dõi,
                phản hồi và hoàn thiện hồ sơ đúng lúc.
              </p>
            </div>

            <div className="max-w-md border-t border-white/25 pt-5 text-sm leading-6 text-white/75">
              <p className="font-medium text-white">Tuyển dụng có ngữ cảnh</p>
              <p className="mt-1">Tin nhắn, hồ sơ và công việc cùng một nhịp xử lý.</p>
            </div>
          </div>
        </aside>

        <section className="relative flex min-h-svh min-w-0 items-center bg-[var(--workspace-canvas)] px-5 py-8 sm:px-8 lg:px-12 xl:px-20">
          <div className="absolute inset-x-0 top-0 h-1 bg-[var(--workspace-action)] lg:hidden" />
          <img
            src="/login-mobile-workspace.jpg"
            alt=""
            aria-hidden="true"
            decoding="async"
            className="pointer-events-none absolute inset-0 z-0 h-full w-full select-none object-cover object-center lg:hidden"
          />
          <div className="pointer-events-none absolute inset-0 z-[1] bg-[linear-gradient(180deg,rgba(241,243,246,0.08)_0%,rgba(241,243,246,0.34)_52%,rgba(241,243,246,0.12)_100%)] lg:hidden" />
          <div className="absolute left-5 top-7 z-10 flex items-center gap-2.5 sm:left-8 lg:hidden">
            <img
              src="/ttsoft-logo.png"
              alt=""
              aria-hidden="true"
              className="size-9 rounded-full object-contain ring-1 ring-[var(--workspace-border)]"
            />
            <span className="text-[1rem] font-semibold tracking-[-0.02em] text-[var(--workspace-ink)]">
              Ting Ting Soft
            </span>
          </div>

          <section className="relative z-10 mx-auto w-full max-w-[28rem] pt-16 sm:pt-14 lg:pt-0">
            <div className="mb-7 border-l-4 border-[var(--workspace-action)] pl-4 sm:mb-8">
              <p className="mb-2 text-xs font-semibold tracking-[0.12em] text-[var(--workspace-action)]">
                KHU VỰC LÀM VIỆC
              </p>
              <h2 className="text-balance text-[clamp(1.875rem,1.55rem+1.1vw,2.35rem)] font-semibold leading-[1.08] tracking-[-0.035em] text-[var(--workspace-ink)]">
                {translate("crm.auth.welcome_back", {
                  _: "Chào mừng bạn trở lại!",
                })}
              </h2>
              <p className="mt-3 text-[0.9375rem] leading-6 text-[var(--workspace-ink-muted)]">
                Đăng nhập để tiếp tục xử lý ứng viên và cuộc trò chuyện của bạn.
              </p>
            </div>

          <div className="border border-[var(--workspace-border)] bg-white p-5 shadow-[0_16px_34px_rgba(48,64,98,0.1)] sm:p-7">
            {showEmailPassword ? (
              <Form className="space-y-4" onSubmit={handleSubmit}>
                <EmailField />
                <PasswordField disabled={loading} />
                <Button
                  type="submit"
                  className="mt-3 h-12 w-full cursor-pointer rounded-[var(--workspace-radius-control)] bg-[var(--workspace-action)] text-sm font-semibold text-white shadow-none transition-[background-color,transform] duration-200 hover:bg-[var(--workspace-action-strong)] active:scale-[0.99] focus-visible:ring-2 focus-visible:ring-[var(--workspace-focus)] focus-visible:ring-offset-2"
                  disabled={loading}
                >
                  {loading ? (
                    <>
                      <Loader2 className="size-4 animate-spin" />
                      {translate("ra.auth.sign_in", { _: "Đăng nhập" })}
                    </>
                  ) : (
                    <>
                      {translate("ra.auth.sign_in", { _: "Đăng nhập" })}
                      <ArrowRight className="size-4" />
                    </>
                  )}
                </Button>
              </Form>
            ) : null}

            {showDivider ? (
              <div className="relative py-5">
                <Separator className="bg-[var(--workspace-border)]" />
                <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-white px-2 text-xs text-[var(--workspace-ink-muted)]">
                  {translate("crm.auth.or_divider", { _: "hoặc" })}
                </span>
              </div>
            ) : null}

            {showSso ? (
              <SSOAuthButton
                className="h-12 w-full rounded-[var(--workspace-radius-control)] border-[var(--workspace-border)] bg-white text-[var(--workspace-ink)] shadow-none transition-[background-color,transform] duration-200 hover:bg-[var(--workspace-surface-muted)] active:scale-[0.99]"
                domain={googleWorkplaceDomain!}
              >
                <GoogleMark />
                {translate("crm.auth.sign_in_google", {
                  _: "Đăng nhập với Google",
                })}
              </SSOAuthButton>
            ) : null}

            {showEmailPassword ? (
              <p className="pt-5 text-center text-sm text-[var(--workspace-ink-muted)]">
                {translate("ra-auth.auth.forgot_password", {
                  _: "Quên mật khẩu?",
                })}{" "}
                <Link
                  to="/forgot-password"
                  className="font-semibold text-[var(--workspace-action-strong)] underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--workspace-focus)]"
                >
                  {translate("crm.auth.recover_now", {
                    _: "Khôi phục ngay",
                  })}
                </Link>
              </p>
            ) : null}
          </div>

          <p className="mt-6 text-center text-xs text-[var(--workspace-ink-muted)]">
            &copy; {new Date().getFullYear()}{" "}
            {translate("crm.auth.footer_tagline", {
              _: "Giải pháp phần mềm Ting Ting",
            })}
          </p>
        </section>
        </section>
      </main>
      <Notification />
    </div>
  );
};

const EmailField = () => {
  const { id, field, isRequired } = useInput({
    source: "email",
    type: "email",
    validate: required(),
  });
  const translate = useTranslate();
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="font-semibold text-[var(--workspace-ink)]">
        {translate("ra.auth.email", { _: "Email" })}
      </Label>
      <div className="relative">
        <Mail
          aria-hidden
          className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-[var(--workspace-ink-muted)]"
        />
        <Input
          id={id}
          type="email"
          autoComplete="email"
          required={isRequired}
          placeholder="ten@congty.vn"
          className="h-12 rounded-[var(--workspace-radius-control)] border-[var(--workspace-border)] bg-white pl-11 text-base text-[var(--workspace-ink)] shadow-none placeholder:text-[var(--workspace-ink-muted)]/75 focus-visible:border-[var(--workspace-focus)] focus-visible:ring-[var(--workspace-focus)]"
          {...field}
        />
      </div>
    </div>
  );
};

const PasswordField = ({ disabled }: { disabled?: boolean }) => {
  const { id, field, isRequired } = useInput({
    source: "password",
    type: "password",
    validate: required(),
  });
  const translate = useTranslate();
  const [show, setShow] = useState(false);
  const Icon = show ? EyeOff : Eye;
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="font-semibold text-[var(--workspace-ink)]">
        {translate("ra.auth.password", { _: "Mật khẩu" })}
      </Label>
      <div className="relative">
        <Lock
          aria-hidden
          className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-[var(--workspace-ink-muted)]"
        />
        <Input
          id={id}
          type={show ? "text" : "password"}
          autoComplete="current-password"
          required={isRequired}
          className="h-12 rounded-[var(--workspace-radius-control)] border-[var(--workspace-border)] bg-white pl-11 pr-11 text-base text-[var(--workspace-ink)] shadow-none focus-visible:border-[var(--workspace-focus)] focus-visible:ring-[var(--workspace-focus)]"
          {...field}
          disabled={disabled}
        />
        <button
          type="button"
          onClick={() => setShow((s) => !s)}
          aria-label={show ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
          className="absolute right-2.5 top-1/2 inline-flex size-9 -translate-y-1/2 items-center justify-center rounded-[var(--workspace-radius-control)] text-[var(--workspace-ink-muted)] transition-colors hover:bg-[var(--workspace-surface-muted)] hover:text-[var(--workspace-ink)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--workspace-focus)]"
        >
          <Icon className="size-4" />
        </button>
      </div>
    </div>
  );
};

const GoogleMark = () => (
  <svg
    aria-hidden
    viewBox="0 0 48 48"
    className="size-4 shrink-0"
    xmlns="http://www.w3.org/2000/svg"
  >
    <path
      fill="#FFC107"
      d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.2-.1-2.4-.4-3.5z"
    />
    <path
      fill="#FF3D00"
      d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3 0 5.8 1.1 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"
    />
    <path
      fill="#4CAF50"
      d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.1 35 26.7 36 24 36c-5.3 0-9.7-3.3-11.3-8L6.1 33.1C9.5 39.6 16.2 44 24 44z"
    />
    <path
      fill="#1976D2"
      d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.3 4.2-4.2 5.6l6.2 5.2C40.9 36 44 30.4 44 24c0-1.2-.1-2.4-.4-3.5z"
    />
  </svg>
);
