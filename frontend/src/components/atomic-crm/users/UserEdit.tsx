import { useState } from "react";
import {
  EditBase,
  email,
  Form,
  required,
  useDataProvider,
  useNotify,
  useRecordContext,
  useRedirect,
  useTranslate,
} from "ra-core";
import { TextInput } from "@/components/admin/text-input";
import { SelectInput } from "@/components/admin/select-input";
import { BooleanInput } from "@/components/admin/boolean-input";
import { Button } from "@/components/ui/button";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { UserAccount } from "../types";
import { UserRoleBadge, UserStatusBadge } from "./UserBadges";
import { ArrowLeft, Check, LoaderCircle, UserCog } from "lucide-react";
import { Link } from "react-router";
import { PageHeading, PageShell } from "../kit";
import "./users.css";

const ROLE_CHOICES = [
  { id: "admin", name: "Quản trị" },
  { id: "recruiter", name: "Tuyển dụng" },
];

const REQUIRED_FIELD = required("Vui lòng nhập thông tin.");
const VALID_EMAIL = email("Email chưa đúng định dạng.");

const UserEditContent = () => {
  const user = useRecordContext<UserAccount>();
  const notify = useNotify();
  const redirect = useRedirect();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const translate = useTranslate();
  const [submitting, setSubmitting] = useState(false);
  if (!user) return null;

  const onSubmit = async (data: Record<string, unknown>) => {
    setSubmitting(true);
    try {
      await dataProvider.update("users", {
        id: user.id,
        previousData: user,
        data: {
          email: data.email,
          full_name: data.full_name,
          role: data.role,
          disabled: data.disabled,
        },
      });
      notify("Đã lưu tài khoản.", { type: "success" });
      redirect("/users");
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section
      className="user-account-form user-account-edit-form mt-4"
      aria-labelledby="user-edit-form-title"
    >
      <header className="user-account-form-header user-account-edit-header">
        <div className="flex min-w-0 items-center gap-3">
          <span className="user-account-form-icon">
            <UserCog className="size-4" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h2 id="user-edit-form-title" className="truncate">
              {user.email}
            </h2>
            <p>Thông tin và quyền truy cập.</p>
          </div>
        </div>
        <span className="user-account-statuses">
          <span>
            <UserRoleBadge />
          </span>
          <span>
            <UserStatusBadge />
          </span>
        </span>
      </header>
      <Form record={user} onSubmit={onSubmit}>
        <div className="user-account-form-body">
          <div className="user-account-field-grid">
            <TextInput
              source="email"
              label="Email"
              type="email"
              isRequired
              validate={[REQUIRED_FIELD, VALID_EMAIL]}
              className="user-account-field user-account-field-wide"
            />
            <TextInput
              source="full_name"
              label="Họ tên"
              isRequired
              validate={REQUIRED_FIELD}
            />
            <SelectInput
              source="role"
              label="Vai trò"
              choices={ROLE_CHOICES}
              isRequired
              validate={REQUIRED_FIELD}
            />
            <div className="user-account-toggle-row user-account-field-wide">
              <BooleanInput source="disabled" label="Vô hiệu hóa tài khoản" />
            </div>
          </div>
          <footer className="user-account-form-actions">
            <Button
              type="submit"
              disabled={submitting}
              className="user-account-submit tt-btn-touch"
            >
              {submitting ? (
                <LoaderCircle
                  className="size-4 animate-spin"
                  aria-hidden="true"
                />
              ) : (
                <Check className="size-4" aria-hidden="true" />
              )}
              {submitting
                ? translate("crm.common.saving")
                : translate("crm.common.save_changes")}
            </Button>
          </footer>
        </div>
      </Form>
    </section>
  );
};

export const UserEdit = () => (
  <EditBase>
    <PageShell size="narrow">
      <PageHeading
        eyebrow="Quản trị truy cập"
        title="Chỉnh sửa tài khoản"
        subtitle="Cập nhật thông tin, quyền và trạng thái."
        actions={
          <Button
            asChild
            variant="outline"
            className="user-account-back tt-btn-touch"
          >
            <Link to="/users">
              <ArrowLeft className="size-4" aria-hidden="true" />
              Tài khoản
            </Link>
          </Button>
        }
      />
      <UserEditContent />
    </PageShell>
  </EditBase>
);
