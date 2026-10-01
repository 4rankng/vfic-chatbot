import { useState } from "react";
import {
  CreateBase,
  email,
  Form,
  minLength,
  required,
  useDataProvider,
  useNotify,
  useRedirect,
} from "ra-core";
import { useHref } from "react-router";
import { Button } from "@/components/base/buttons/button";
import { UserPlus } from "lucide-react";
import { FormSelect, FormTextInput, PageHeading, PageShell } from "../kit";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import "./users.css";

const ROLE_CHOICES = [
  { id: "admin", name: "Quản trị" },
  { id: "recruiter", name: "Tuyển dụng" },
];

const REQUIRED_FIELD = required("Vui lòng nhập thông tin.");
const VALID_EMAIL = email("Email chưa đúng định dạng.");
const PASSWORD_LENGTH = minLength(8, "Mật khẩu phải có ít nhất 8 ký tự.");
const PASSWORD_CONFIRMATION = (
  value: string,
  values: Record<string, unknown>,
) => (value === values.password ? undefined : "Mật khẩu xác nhận không khớp.");

export const UserCreate = () => {
  const notify = useNotify();
  const redirect = useRedirect();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const listHref = useHref("/users");

  const onSubmit = async (data: Record<string, unknown>) => {
    if (isSubmitting) return;
    if (data.password !== data.confirm_password) {
      notify("Mật khẩu xác nhận không khớp.", { type: "error" });
      return;
    }
    const { confirm_password: _confirmPassword, ...payload } = data;
    setIsSubmitting(true);
    try {
      await dataProvider.create("users", { data: payload });
      notify("Đã tạo tài khoản.", { type: "success" });
      redirect("/users");
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <CreateBase resource="users">
      <PageShell size="narrow">
        <PageHeading
          eyebrow="Quản trị truy cập"
          title="Tạo tài khoản"
          subtitle="Tạo đăng nhập và quyền cho thành viên nội bộ."
        />
        <section
          className="user-account-form mt-4"
          aria-labelledby="user-create-form-title"
        >
          <header className="user-account-form-header">
            <div className="user-account-form-heading">
              <span className="user-account-form-icon">
                <UserPlus className="size-4" aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <h2 id="user-create-form-title">Thông tin đăng nhập</h2>
                <p>Email là tên đăng nhập.</p>
              </div>
            </div>
          </header>
          <Form onSubmit={onSubmit} noValidate>
            <div className="user-account-form-body">
              <div className="user-account-field-grid">
                <FormTextInput
                  source="email"
                  label="Email"
                  type="email"
                  autoComplete="email"
                  isRequired
                  validate={[REQUIRED_FIELD, VALID_EMAIL]}
                  disabled={isSubmitting}
                  className="user-account-field user-account-field-wide"
                />
                <FormTextInput
                  source="full_name"
                  label="Họ và tên"
                  autoComplete="name"
                  isRequired
                  validate={REQUIRED_FIELD}
                  disabled={isSubmitting}
                  className="user-account-field"
                />
                <FormSelect
                  source="role"
                  label="Vai trò"
                  choices={ROLE_CHOICES}
                  placeholder="Chọn vai trò"
                  defaultValue="recruiter"
                  isRequired
                  validate={REQUIRED_FIELD}
                  disabled={isSubmitting}
                  className="user-account-field"
                />
                <FormTextInput
                  source="password"
                  label="Mật khẩu"
                  type="password"
                  autoComplete="new-password"
                  isRequired
                  validate={[REQUIRED_FIELD, PASSWORD_LENGTH]}
                  hint="Ít nhất 8 ký tự."
                  disabled={isSubmitting}
                  className="user-account-field"
                />
                <FormTextInput
                  source="confirm_password"
                  label="Xác nhận mật khẩu"
                  type="password"
                  autoComplete="new-password"
                  isRequired
                  validate={[REQUIRED_FIELD, PASSWORD_CONFIRMATION]}
                  disabled={isSubmitting}
                  className="user-account-field"
                />
              </div>
              <footer className="user-account-form-actions">
                <Button
                  href={listHref}
                  color="secondary"
                  size="md"
                  className="uu-scope user-account-secondary-action min-h-11 max-[760px]:w-full"
                  isDisabled={isSubmitting}
                >
                  Hủy
                </Button>
                <Button
                  type="submit"
                  size="md"
                  className="uu-scope user-account-submit min-h-11 max-[760px]:w-full"
                  isDisabled={isSubmitting}
                  isLoading={isSubmitting}
                  showTextWhileLoading
                >
                  {isSubmitting ? "Đang tạo" : "Tạo tài khoản"}
                </Button>
              </footer>
            </div>
          </Form>
        </section>
      </PageShell>
    </CreateBase>
  );
};
