import { useState } from "react";
import {
  Form,
  email,
  required,
  useInput,
  useLogin,
  ValidationError,
} from "ra-core";
import type { FieldValues, SubmitHandler } from "react-hook-form";
import { Link } from "react-router";
import { ArrowRight, Eye, EyeOff, Lock, Mail } from "lucide-react";

import { Notification } from "@/components/admin/notification";
import { Button } from "@/components/base/buttons/button";
import { ButtonUtility } from "@/components/base/buttons/button-utility";
import { InputBase, TextField } from "@/components/base/input/input";
import { Label } from "@/components/base/input/label";
import { HintText } from "@/components/base/input/hint-text";
import { useInstallationContext } from "../installation/installation-context";
import { AuthShell } from "./AuthShell";

/**
 * The sign-in form is the console's Untitled UI surface: `TextField` /
 * `Label` / `InputBase` for the two fields and `Button` for the submit.
 *
 * Two rules carry it. `validationBehavior="aria"` keeps React Aria's default
 * `native` behaviour from writing `required` onto the input — the browser would
 * then block the submit and show its own bubble instead of letting react-admin
 * run the validator and raise the console's Vietnamese error. `uu-scope` re-binds
 * the four utility names this console and Untitled UI both define
 * (`bg-primary`, `bg-secondary`, `text-primary`, `border-primary`); without it the
 * field paints with the brand coral fill instead of a white surface. See
 * `src/styles/untitledui-theme.css`.
 *
 * The fields compose `InputBase` rather than the composed `Input` on purpose:
 * the password field keeps the console's own reveal control, and the composed
 * wrapper would add a second, English-labelled eye next to it.
 */
export const LoginPage = ({ redirectTo }: { redirectTo?: string }) => {
  const { manifest } = useInstallationContext();
  const [loading, setLoading] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const login = useLogin();
  const activeName =
    manifest.lifecycle === "ACTIVE"
      ? manifest.branding?.app_name?.trim() ||
        manifest.customer_identity?.display_name.trim()
      : null;

  const handleSubmit: SubmitHandler<FieldValues> = async (values) => {
    if (loading) return;
    setLoading(true);
    setLoginError(null);
    try {
      await login(values, redirectTo);
    } catch (error: unknown) {
      setLoginError(
        error instanceof Error && error.message
          ? error.message
          : "Đăng nhập không thành công. Vui lòng thử lại.",
      );
    } finally {
      setLoading(false);
    }
  };

  const productName = activeName ?? "TingHire";

  return (
    <>
      <AuthShell productName={productName}>
        <section aria-labelledby="login-title" className="uu-scope w-full">
          <h1
            id="login-title"
            className="mb-5 text-page-title font-semibold tracking-tight"
          >
            Đăng nhập
          </h1>

          <Form
            className="grid gap-3"
            onSubmit={handleSubmit}
            noValidate
            disableInvalidFormNotification
          >
            <EmailField disabled={loading} />
            <PasswordField disabled={loading} />
            {loginError ? (
              <p
                role="alert"
                className="rounded-lg border border-error_subtle bg-error-primary px-4 py-3 text-body text-error-primary"
              >
                {loginError}
              </p>
            ) : null}
            <Button
              type="submit"
              size="sm"
              className="mt-1 w-full"
              isDisabled={loading}
              isLoading={loading}
              showTextWhileLoading
              iconTrailing={loading ? undefined : ArrowRight}
            >
              Đăng nhập
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

const EmailField = ({ disabled }: { disabled?: boolean }) => {
  const { id, field, fieldState, isRequired } = useInput({
    source: "email",
    type: "email",
    validate: [
      required("Vui lòng nhập email."),
      (value: string) => email("Nhập địa chỉ email hợp lệ.")(value.trim()),
    ],
  });
  return (
    <TextField
      id={id}
      className="uu-scope gap-1.5"
      name={field.name}
      type="email"
      value={typeof field.value === "string" ? field.value : ""}
      onChange={(value: string) => field.onChange(value)}
      onBlur={field.onBlur}
      validationBehavior="aria"
      isRequired={isRequired}
      isDisabled={disabled}
      isInvalid={Boolean(fieldState.error)}
    >
      <Label>Email</Label>
      <InputBase
        ref={field.ref}
        type="email"
        icon={Mail}
        autoComplete="email"
        isDisabled={disabled}
        isInvalid={Boolean(fieldState.error)}
        size="sm"
      />
      {fieldState.error?.message ? (
        <HintText isInvalid role="alert">
          <ValidationError error={fieldState.error.message} />
        </HintText>
      ) : null}
    </TextField>
  );
};

const PasswordField = ({ disabled }: { disabled?: boolean }) => {
  const { id, field, fieldState, isRequired } = useInput({
    source: "password",
    type: "password",
    validate: required("Vui lòng nhập mật khẩu."),
  });
  const [visible, setVisible] = useState(false);
  return (
    <TextField
      id={id}
      className="uu-scope gap-1.5"
      name={field.name}
      type={visible ? "text" : "password"}
      value={typeof field.value === "string" ? field.value : ""}
      onChange={(value: string) => field.onChange(value)}
      onBlur={field.onBlur}
      validationBehavior="aria"
      isRequired={isRequired}
      isDisabled={disabled}
      isInvalid={Boolean(fieldState.error)}
    >
      <Label>Mật khẩu</Label>
      <div className="relative w-full">
        {/*
          `[&>button]:hidden` suppresses the primitive's own password eye: the
          reveal control here is the console's, so its accessible name stays
          Vietnamese.
        */}
        <InputBase
          ref={field.ref}
          size="sm"
          type={visible ? "text" : "password"}
          icon={Lock}
          autoComplete="current-password"
          isDisabled={disabled}
          isInvalid={Boolean(fieldState.error)}
          inputClassName="pr-12"
          wrapperClassName="[&>button]:hidden"
        />
        <ButtonUtility
          data-allow-tall
          tooltip={visible ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
          color="tertiary"
          className="auth-password-action absolute right-0.5 top-1/2 -translate-y-1/2"
          onClick={() => setVisible((current) => !current)}
          isDisabled={disabled}
          icon={visible ? <EyeOff /> : <Eye />}
        />
      </div>
      {fieldState.error?.message ? (
        <HintText isInvalid role="alert">
          <ValidationError error={fieldState.error.message} />
        </HintText>
      ) : null}
    </TextField>
  );
};
