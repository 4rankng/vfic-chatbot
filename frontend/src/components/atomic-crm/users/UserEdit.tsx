import { useState } from "react";
import {
  EditBase,
  Form,
  useDataProvider,
  useNotify,
  useRecordContext,
  useRedirect,
} from "ra-core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TextInput } from "@/components/admin/text-input";
import { SelectInput } from "@/components/admin/select-input";
import { BooleanInput } from "@/components/admin/boolean-input";
import { TopToolbar } from "../layout/TopToolbar";
import { Button } from "@/components/ui/button";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { UserAccount } from "../types";
import { UserRoleBadge, UserStatusBadge } from "./UserBadges";

const ROLE_CHOICES = [
  { id: "admin", name: "Quản trị" },
  { id: "recruiter", name: "Tuyển dụng" },
];

const UserEditContent = () => {
  const user = useRecordContext<UserAccount>();
  const notify = useNotify();
  const redirect = useRedirect();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const [submitting, setSubmitting] = useState(false);
  if (!user) return null;

  const onSubmit = async (data: Record<string, unknown>) => {
    setSubmitting(true);
    try {
      await dataProvider.update("users", {
        id: user.id,
        previousData: user,
        data: {
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
    <Card className="mt-4 max-w-2xl">
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-3 text-base">
          <span>{user.email}</span>
          <span className="flex gap-2">
            <UserRoleBadge />
            <UserStatusBadge />
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-2">
        <Form record={user} onSubmit={onSubmit}>
          <div className="flex flex-col gap-4">
            <TextInput source="email" label="Email" disabled />
            <TextInput source="full_name" label="Họ tên" isRequired />
            <SelectInput
              source="role"
              label="Vai trò"
              choices={ROLE_CHOICES}
              isRequired
            />
            <BooleanInput source="disabled" label="Vô hiệu hóa tài khoản" />
            <Button type="submit" disabled={submitting}>
              Lưu tài khoản
            </Button>
          </div>
        </Form>
      </CardContent>
    </Card>
  );
};

export const UserEdit = () => (
  <EditBase>
    <TopToolbar>
      <h2 className="mr-auto text-xl font-semibold">Chỉnh sửa tài khoản</h2>
    </TopToolbar>
    <UserEditContent />
  </EditBase>
);
