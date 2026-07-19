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
import { Check, UserPlus } from "lucide-react";
import { AlternateCard, PageHeading, PageShell } from "../kit";
import type { CrmDataProvider } from "../providers/rest/dataProvider";

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
          subtitle="Thêm thành viên nội bộ và chỉ định quyền phù hợp với công việc."
        />
        <AlternateCard
          className="mt-4"
          icon={<UserPlus className="size-4" aria-hidden="true" />}
          title="Thông tin tài khoản"
          description="Email được dùng để đăng nhập vào hệ thống."
          bodyClassName="p-5 sm:p-6"
        >
          <Form onSubmit={onSubmit}>
            <div className="flex flex-col gap-5">
              <TextInput source="email" label="Email" type="email" isRequired />
              <TextInput source="full_name" label="Họ tên" isRequired />
              <SelectInput
                source="role"
                label="Vai trò"
                choices={ROLE_CHOICES}
                defaultValue="recruiter"
                isRequired
              />
              <TextInput
                source="password"
                label="Mật khẩu"
                type="password"
                isRequired
              />
              <TextInput
                source="confirm_password"
                label="Xác nhận mật khẩu"
                type="password"
                isRequired
              />
              <div className="flex justify-end border-t border-[var(--tt-border)] pt-5">
                <Button
                  type="submit"
                  disabled={isSubmitting}
                  className="min-h-11 sm:min-h-10"
                >
                  <Check className="size-4" aria-hidden="true" />
                  Tạo tài khoản
                </Button>
              </div>
            </div>
          </Form>
        </AlternateCard>
      </PageShell>
    </CreateBase>
  );
};
