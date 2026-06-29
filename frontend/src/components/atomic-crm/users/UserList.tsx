import { CanAccess, ListBase, useTranslate } from "ra-core";
import { CreateButton } from "@/components/admin/create-button";
import { DataTable } from "@/components/admin/data-table";
import { TextField } from "@/components/admin/text-field";
import { DateField } from "@/components/admin/date-field";
import { TopToolbar } from "../layout/TopToolbar";
import { Card } from "@/components/ui/card";
import { ShieldOff } from "lucide-react";
import { UserActions } from "./UserActions";
import { UserRoleBadge, UserStatusBadge } from "./UserBadges";

const AccessDenied = () => {
  const translate = useTranslate();
  return (
    <Card className="mt-4">
      <div className="flex flex-col items-center gap-3 p-10 text-center text-muted-foreground">
        <ShieldOff className="size-10 opacity-60" />
        <p className="text-base font-medium text-foreground">
          {translate("ra.page.access_denied", { _: "Access denied" })}
        </p>
        <p className="max-w-sm text-sm">
          {translate("crm.users.access_denied_help", {
            _: "Only administrators can manage users. Ask an admin to grant you access.",
          })}
        </p>
      </div>
    </Card>
  );
};

export const UserList = () => {
  const translate = useTranslate();
  return (
    <CanAccess resource="users" action="list" accessDenied={<AccessDenied />}>
      <ListBase perPage={25} sort={{ field: "created_at", order: "DESC" }}>
        <TopToolbar>
          <h2 className="mr-auto text-xl font-semibold">
            {translate("resources.users.name", { smart_count: 2 })}
          </h2>
          <CreateButton />
        </TopToolbar>
        <div className="mt-4">
          <DataTable bulkActionButtons={false}>
            <DataTable.Col source="full_name" label="Họ tên">
              <TextField source="full_name" className="font-semibold" />
            </DataTable.Col>
            <DataTable.Col source="email" label="Email" />
            <DataTable.Col source="role" label="Vai trò">
              <UserRoleBadge />
            </DataTable.Col>
            <DataTable.Col source="disabled" label="Trạng thái">
              <UserStatusBadge />
            </DataTable.Col>
            <DataTable.Col source="created_at" label="Ngày tạo">
              <DateField source="created_at" showTime />
            </DataTable.Col>
            <DataTable.Col label="Thao tác">
              <UserActions />
            </DataTable.Col>
          </DataTable>
        </div>
      </ListBase>
    </CanAccess>
  );
};
