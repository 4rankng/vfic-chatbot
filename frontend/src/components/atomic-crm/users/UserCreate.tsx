import { useState } from "react";
import {
  CreateBase,
  Form,
  useDataProvider,
  useNotify,
  useRedirect,
} from "ra-core";
import { TextInput } from "@/components/admin/text-input";
import { SelectInput } from "@/components/admin/select-input";
import { Button } from "@/components/ui/button";
import { Check, LoaderCircle, UserPlus } from "lucide-react";
import { Link } from "react-router";
import { PageHeading, PageShell } from "../kit";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import "./users.css";

const ROLE_CHOICES = [
  { id: "admin", name: "Quản trị" },
  { id: "recruiter", name: "Tuyển dụng" },
];

export const UserCreate = () => {
  const notify = useNotify();
  const redirect = useRedirect();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const onSubmit = async (data: Record<string, unknown>) => {
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
          <Form onSubmit={onSubmit}>
            <div className="user-account-form-body">
              <div className="user-account-field-grid">
                <TextInput
                  source="email"
                  label="Email"
                  type="email"
                  isRequired
                  className="user-account-field user-account-field-wide"
                />
                <TextInput
                  source="full_name"
                  label="Họ và tên"
                  isRequired
                  className="user-account-field"
                />
                <SelectInput
                  source="role"
                  label="Vai trò"
                  choices={ROLE_CHOICES}
                  defaultValue="recruiter"
                  isRequired
                  className="user-account-field"
                />
                <TextInput
                  source="password"
                  label="Mật khẩu"
                  type="password"
                  isRequired
                  className="user-account-field"
                />
                <TextInput
                  source="confirm_password"
                  label="Xác nhận mật khẩu"
                  type="password"
                  isRequired
                  className="user-account-field"
                />
              </div>
              <footer className="user-account-form-actions">
                <Button
                  asChild
                  type="button"
                  variant="outline"
                  className="user-account-secondary-action tt-btn-touch"
                >
                  <Link to="/users">Hủy</Link>
                </Button>
                <Button
                  type="submit"
                  disabled={isSubmitting}
                  className="user-account-submit tt-btn-touch"
                >
                  {isSubmitting ? (
                    <LoaderCircle
                      className="size-4 animate-spin"
                      aria-hidden="true"
                    />
                  ) : (
                    <Check className="size-4" aria-hidden="true" />
                  )}
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
