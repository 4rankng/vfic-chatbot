import { useState } from "react";
import { CreateBase, Form, useDataProvider, useNotify, useRedirect } from "ra-core";
import { Card, CardContent } from "@/components/ui/card";
import { TextInput } from "@/components/admin/text-input";
import { SelectInput } from "@/components/admin/select-input";
import { TopToolbar } from "../layout/TopToolbar";
import { Button } from "@/components/ui/button";
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
      <div className="mx-auto w-full max-w-2xl">
        <TopToolbar className="items-center">
          <h2 className="mr-auto text-xl font-semibold">Tạo tài khoản</h2>
        </TopToolbar>
        <Card className="mt-4 w-full">
          <CardContent className="pt-6">
            <Form onSubmit={onSubmit}>
              <div className="flex flex-col gap-4">
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
                <Button type="submit" disabled={isSubmitting}>
                  Tạo tài khoản
                </Button>
              </div>
            </Form>
          </CardContent>
        </Card>
      </div>
    </CreateBase>
  );
};
