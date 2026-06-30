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
 * Layout follows the VFIC knowledge-center visual language: paper surface,
 * dark ink actions, and a transparent product illustration.
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
    <div className="kb-scope login-paper min-h-svh overflow-hidden text-foreground">
      <main className="mx-auto flex min-h-svh w-full max-w-[620px] items-center justify-center px-5 py-8 sm:px-8">
        <section className="mx-auto flex w-full max-w-[470px] flex-col justify-center">
          <div className="mb-6 space-y-3 text-center sm:mb-8">
            <div className="flex items-center justify-center gap-4">
              <img
                src="/ttsoft-logo.png"
                alt=""
                aria-hidden="true"
                className="size-12 shrink-0 rounded-md object-contain"
              />
              <p className="text-xl font-semibold leading-none tracking-tight text-foreground sm:text-2xl">
                Ting Ting Soft
              </p>
            </div>
            <div className="space-y-3">
              <h1 className="kb-display text-balance text-[clamp(1.65rem,3.05vw,2.65rem)] leading-none text-foreground">
                {translate("crm.auth.welcome_back", {
                  _: "Chào mừng bạn trở lại!",
                })}
              </h1>
            </div>
          </div>

          <div className="rounded-md border border-border bg-card/92 p-4 shadow-xs backdrop-blur sm:p-6">
            {showEmailPassword ? (
              <Form className="space-y-4" onSubmit={handleSubmit}>
                <EmailField />
                <PasswordField disabled={loading} />
                <Button
                  type="submit"
                  className="mt-2 h-12 w-full cursor-pointer rounded-md text-sm font-semibold"
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
                <Separator />
                <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-card px-2 text-xs text-muted-foreground">
                  {translate("crm.auth.or_divider", { _: "hoặc" })}
                </span>
              </div>
            ) : null}

            {showSso ? (
              <SSOAuthButton
                className="h-12 w-full rounded-md"
                domain={googleWorkplaceDomain!}
              >
                <GoogleMark />
                {translate("crm.auth.sign_in_google", {
                  _: "Đăng nhập với Google",
                })}
              </SSOAuthButton>
            ) : null}

            {showEmailPassword ? (
              <p className="pt-5 text-center text-sm text-muted-foreground">
                {translate("ra-auth.auth.forgot_password", {
                  _: "Quên mật khẩu?",
                })}{" "}
                <Link
                  to="/forgot-password"
                  className="font-semibold text-foreground underline-offset-4 hover:underline"
                >
                  {translate("crm.auth.recover_now", {
                    _: "Khôi phục ngay",
                  })}
                </Link>
              </p>
            ) : null}
          </div>

          <p className="mt-6 text-center text-xs text-muted-foreground">
            &copy; {new Date().getFullYear()}{" "}
            {translate("crm.auth.footer_tagline", {
              _: "Giải pháp phần mềm Ting Ting",
            })}
          </p>
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
      <Label htmlFor={id} className="font-semibold text-muted-foreground">
        {translate("ra.auth.email", { _: "Email" })}
      </Label>
      <div className="relative">
        <Mail
          aria-hidden
          className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          id={id}
          type="email"
          autoComplete="email"
          required={isRequired}
          placeholder="you@example.com"
          className="h-12 rounded-md bg-background/70 pl-11 text-base shadow-none placeholder:text-muted-foreground/70"
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
      <Label htmlFor={id} className="font-semibold text-muted-foreground">
        {translate("ra.auth.password", { _: "Mật khẩu" })}
      </Label>
      <div className="relative">
        <Lock
          aria-hidden
          className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          id={id}
          type={show ? "text" : "password"}
          autoComplete="current-password"
          required={isRequired}
          className="h-12 rounded-md bg-background/70 pl-11 pr-11 text-base shadow-none"
          {...field}
          disabled={disabled}
        />
        <button
          type="button"
          onClick={() => setShow((s) => !s)}
          aria-label={show ? "Hide password" : "Show password"}
          className="absolute right-2.5 top-1/2 inline-flex size-8 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
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
