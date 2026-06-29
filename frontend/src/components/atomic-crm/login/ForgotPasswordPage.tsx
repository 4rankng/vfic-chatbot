import { useState } from "react";
import { Form, useNotify } from "ra-core";
import type { SubmitHandler, FieldValues } from "react-hook-form";
import { Link, useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { TextInput } from "@/components/admin/text-input";
import { Notification } from "@/components/admin/notification";
import { useConfigurationContext } from "@/components/atomic-crm/root/ConfigurationContext";
import {
  requestPasswordResetOtp,
  resetPasswordWithOtp,
} from "./passwordRecoveryService";

type Step = "email" | "otp";

export const ForgotPasswordPage = () => {
  const { darkModeLogo, title } = useConfigurationContext();
  const notify = useNotify();
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);

  const submitEmail: SubmitHandler<FieldValues> = async (values) => {
    const nextEmail = String(values.email ?? "").trim().toLowerCase();
    if (!nextEmail) {
      notify("Vui lòng nhập email.", { type: "error" });
      return;
    }
    setLoading(true);
    try {
      await requestPasswordResetOtp(nextEmail);
      setEmail(nextEmail);
      setStep("otp");
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
      navigate("/");
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex">
      <div className="relative grid w-full lg:grid-cols-2">
        <div className="relative hidden h-full flex-col bg-muted p-10 text-white dark:border-r lg:flex">
          <div className="absolute inset-0 bg-zinc-900" />
          <div className="relative z-20 flex items-center text-lg font-medium">
            <img className="h-6 mr-2" src={darkModeLogo} alt={title} />
            {title}
          </div>
        </div>
        <div className="flex w-full flex-col justify-center p-4 lg:p-8">
          <div className="w-full space-y-6 lg:mx-auto lg:w-[380px]">
            <div className="text-center">
              <h1 className="text-2xl font-semibold tracking-tight">
                Khôi phục mật khẩu
              </h1>
              <p className="mt-2 text-sm text-muted-foreground">
                {step === "email"
                  ? "Nhập email tài khoản để nhận mã OTP."
                  : "Nhập mã OTP và mật khẩu mới."}
              </p>
            </div>

            {step === "email" ? (
              <Form className="space-y-8" onSubmit={submitEmail}>
                <TextInput label="Email" source="email" type="email" isRequired />
                <Button type="submit" className="w-full" disabled={loading}>
                  Gửi mã OTP
                </Button>
              </Form>
            ) : (
              <Form className="space-y-8" onSubmit={submitOtp}>
                <TextInput
                  label="Email"
                  source="email"
                  type="email"
                  defaultValue={email}
                  disabled
                />
                <TextInput label="Mã OTP" source="otp" isRequired />
                <TextInput
                  label="Mật khẩu mới"
                  source="new_password"
                  type="password"
                  isRequired
                />
                <TextInput
                  label="Xác nhận mật khẩu"
                  source="confirm_password"
                  type="password"
                  isRequired
                />
                <Button type="submit" className="w-full" disabled={loading}>
                  Đổi mật khẩu
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  disabled={loading}
                  onClick={() => setStep("email")}
                >
                  Gửi lại mã
                </Button>
              </Form>
            )}

            <Link to="/" className="block text-center text-sm hover:underline">
              Quay lại đăng nhập
            </Link>
          </div>
        </div>
      </div>
      <Notification />
    </div>
  );
};
