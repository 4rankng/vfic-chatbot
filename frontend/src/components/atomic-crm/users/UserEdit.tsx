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
import { ArrowLeft } from "lucide-react";
import { Link } from "react-router";

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
    <Card className="mt-4 w-full">
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-3 text-section-title">
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
            <TextInput source="email" label="Email" type="email" isRequired />
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
    <div className="mx-auto w-full max-w-2xl">
      <TopToolbar className="items-center">
        <h2 className="mr-auto text-content-title font-semibold">Chỉnh sửa tài khoản</h2>
        <Button asChild variant="outline" size="sm">
          <Link to="/users">
            <ArrowLeft className="size-4" />
            Quay lại
          </Link>
        </Button>
      </TopToolbar>
      <UserEditContent />
    </div>
  </EditBase>
);
