import { useEffect, useRef, useState } from "react";
import {
  Form,
  required,
  useInput,
  useLogin,
  useNotify,
  useTranslate,
} from "ra-core";
import type { SubmitHandler, FieldValues } from "react-hook-form";
import { Link, useLocation, useNavigate } from "react-router";
import { Eye, EyeOff, Loader2, Lock, Mail } from "lucide-react";
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
 * Layout: two-column split.
 *   - Left: sign-in form (email/password or Google Workspace SSO).
 *   - Right (desktop only): brand hero illustration (public/bg.avif) depicting a
 *     CRM dashboard + chat widget that mirrors the product itself.
 *
 * @see {@link https://marmelab.com/shadcn-admin-kit/docs/loginpage LoginPage documentation}
 * @see {@link https://marmelab.com/shadcn-admin-kit/docs/security Security documentation}
 */
export const LoginPage = (props: { redirectTo?: string }) => {
  const { googleWorkplaceDomain, disableEmailPasswordAuthentication } =
    useConfigurationContext();
  const { redirectTo } = props;
  const [loading, setLoading] = useState(false);
  const hasDisplayedRecoveryNotification = useRef(false);
  const location = useLocation();
  const navigate = useNavigate();
  const login = useLogin();
  const notify = useNotify();
  const translate = useTranslate();

  useEffect(() => {
    const searchParams = new URLSearchParams(location.search);
    const shouldNotify = searchParams.get("passwordRecoveryEmailSent") === "1";

    if (!shouldNotify || hasDisplayedRecoveryNotification.current) {
      return;
    }

    hasDisplayedRecoveryNotification.current = true;
    notify("crm.auth.recovery_email_sent", {
      type: "success",
      messageArgs: {
        _: "If you're a registered user, you should receive a password recovery email shortly.",
      },
    });

    searchParams.delete("passwordRecoveryEmailSent");
    const nextSearch = searchParams.toString();
    navigate(
      {
        pathname: location.pathname,
        search: nextSearch ? `?${nextSearch}` : "",
      },
      { replace: true },
    );
  }, [location.pathname, location.search, navigate, notify]);

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
    <div className="min-h-screen bg-background">
      <div className="grid min-h-screen w-full lg:grid-cols-[minmax(0,520px)_1fr]">
        {/* Left: sign-in form */}
        <div className="flex flex-col p-6 sm:p-10">
          <div className="flex flex-1 items-center justify-center py-10">
            <div className="w-full max-w-sm space-y-7">
              <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight">
                {translate("crm.auth.welcome_back", { _: "Welcome back" })}
              </h1>

              {showEmailPassword ? (
                <Form className="space-y-4" onSubmit={handleSubmit}>
                  <EmailField />
                  <PasswordField disabled={loading} />
                  <Button
                    type="submit"
                    className="h-11 w-full cursor-pointer text-sm font-medium"
                    disabled={loading}
                  >
                    {loading ? (
                      <>
                        <Loader2 className="size-4 animate-spin" />
                        {translate("ra.auth.sign_in", { _: "Sign in" })}
                      </>
                    ) : (
                      translate("ra.auth.sign_in", { _: "Sign in" })
                    )}
                  </Button>
                </Form>
              ) : null}

              {showDivider ? (
                <div className="relative">
                  <Separator />
                  <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-background px-2 text-xs text-muted-foreground">
                    {translate("crm.auth.or_divider", { _: "or" })}
                  </span>
                </div>
              ) : null}

              {showSso ? (
                <SSOAuthButton
                  className="h-11 w-full"
                  domain={googleWorkplaceDomain!}
                >
                  <GoogleMark />
                  {translate("crm.auth.sign_in_google", {
                    _: "Sign in with Google",
                  })}
                </SSOAuthButton>
              ) : null}

              {showEmailPassword ? (
                <p className="text-center text-sm text-muted-foreground">
                  {translate("ra-auth.auth.forgot_password", {
                    _: "Forgot password?",
                  })}{" "}
                  <Link
                    to="/forgot-password"
                    className="font-medium text-foreground underline-offset-4 hover:underline"
                  >
                    {translate("crm.auth.recover_now", {
                      _: "Recover now",
                    })}
                  </Link>
                </p>
              ) : null}
            </div>
          </div>

          <p className="text-center text-xs text-muted-foreground lg:text-left">
            &copy; {new Date().getFullYear()}{" "}
            {translate("crm.auth.footer_tagline", {
              _: "Ting Ting Software Solution",
            })}
          </p>
        </div>

        {/* Right: brand hero illustration (desktop only) */}
        <aside className="relative hidden overflow-hidden lg:flex">
          {/* Hero illustration (public/bg.avif) — a CRM dashboard + chat-widget
              scene that mirrors the product itself. Calm, light composition so
              it reads as a hero without competing with the sign-in form. */}
          <div
            aria-hidden
            className="absolute inset-0 bg-cover bg-center"
            style={{ backgroundImage: "url('/bg.avif')" }}
          />
          {/* Left-edge scrim blends the illustration into the form column;
              stronger in dark mode where the bright image meets a dark surface. */}
          <div
            aria-hidden
            className="absolute inset-0 bg-gradient-to-r from-background/70 via-background/10 to-transparent dark:from-background/95 dark:via-background/40"
          />
        </aside>
      </div>
      <Notification />
    </div>
  );
};

/* ---------- form field components ---------- */

const EmailField = () => {
  const { id, field, isRequired } = useInput({
    source: "email",
    type: "email",
    validate: required(),
  });
  const translate = useTranslate();
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{translate("ra.auth.email", { _: "Email" })}</Label>
      <div className="relative">
        <Mail
          aria-hidden
          className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          id={id}
          type="email"
          autoComplete="email"
          required={isRequired}
          placeholder="you@example.com"
          className="h-11 pl-10"
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
      <Label htmlFor={id}>
        {translate("ra.auth.password", { _: "Password" })}
      </Label>
      <div className="relative">
        <Lock
          aria-hidden
          className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          id={id}
          type={show ? "text" : "password"}
          autoComplete="current-password"
          required={isRequired}
          className="h-11 pl-10 pr-10"
          {...field}
          disabled={disabled}
        />
        <button
          type="button"
          onClick={() => setShow((s) => !s)}
          aria-label={show ? "Hide password" : "Show password"}
          className="absolute right-2 top-1/2 inline-flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <Icon className="size-4" />
        </button>
      </div>
    </div>
  );
};

/* ---------- small helpers ---------- */

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
