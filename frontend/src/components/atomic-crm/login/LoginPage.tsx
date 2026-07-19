import { useState } from "react";
import { Form, required, useInput, useLogin, useNotify } from "ra-core";
import type { FieldValues, SubmitHandler } from "react-hook-form";
import { Link } from "react-router";
import { ArrowRight, Eye, EyeOff, Lock, Mail } from "lucide-react";

import { Notification } from "@/components/admin/notification";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useInstallationContext } from "../installation/installation-context";
import { AuthShell } from "./AuthShell";

export const LoginPage = ({ redirectTo }: { redirectTo?: string }) => {
  const { manifest } = useInstallationContext();
  const [loading, setLoading] = useState(false);
  const login = useLogin();
  const notify = useNotify();
  const activeName =
    manifest.lifecycle === "ACTIVE"
      ? manifest.branding?.app_name?.trim() ||
        manifest.customer_identity?.display_name.trim()
      : null;

  const handleSubmit: SubmitHandler<FieldValues> = (values) => {
    setLoading(true);
    login(values, redirectTo)
      .catch((error: unknown) => {
        notify(
          error instanceof Error && error.message
            ? error.message
            : "Đăng nhập không thành công. Vui lòng thử lại.",
          { type: "error" },
        );
      })
      .finally(() => setLoading(false));
  };

  const productName = activeName ?? "Ting Ting";

  return (
    <>
      <AuthShell productName={productName}>
        <section
          aria-labelledby="login-title"
          className="tt-card tt-card-border rounded-xl border border-base-300 bg-base-100 p-6 shadow-sm sm:p-7"
        >
          <h1
            id="login-title"
            className="mb-5 text-page-title font-semibold tracking-tight"
          >
            Đăng nhập
          </h1>

          <Form className="grid gap-5" onSubmit={handleSubmit}>
            <EmailField />
            <PasswordField disabled={loading} />
            <Button
              type="submit"
              className="mt-2 min-h-12 w-full"
              disabled={loading}
            >
              {loading ? (
                <span
                  className="tt-loading tt-loading-spinner tt-loading-sm"
                  aria-hidden="true"
                />
              ) : null}
              Đăng nhập
              {!loading ? <ArrowRight /> : null}
            </Button>
          </Form>
          <p className="mt-5 border-t border-base-300 pt-5 text-center text-body text-muted-foreground">
            <Link
              to="/forgot-password"
              className="font-medium underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-4"
            >
              Quên mật khẩu?
            </Link>
          </p>
        </section>
      </AuthShell>
      <Notification />
    </>
  );
};

const EmailField = () => {
  const { id, field, isRequired } = useInput({
    source: "email",
    type: "email",
    validate: required(),
  });
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>Email</Label>
      <div className="relative">
        <Mail
          className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
        <Input
          id={id}
          type="email"
          autoComplete="email"
          required={isRequired}
          className="min-h-12 pl-11"
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
  const [visible, setVisible] = useState(false);
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>Mật khẩu</Label>
      <div className="relative">
        <Lock
          className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
        <Input
          id={id}
          type={visible ? "text" : "password"}
          autoComplete="current-password"
          required={isRequired}
          disabled={disabled}
          className="min-h-12 px-11"
          {...field}
        />
        <button
          type="button"
          className="absolute right-2 top-1/2 flex size-10 -translate-y-1/2 items-center justify-center rounded-md focus-visible:outline-2"
          aria-label={visible ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
          onClick={() => setVisible((current) => !current)}
        >
          {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </button>
      </div>
    </div>
  );
};
