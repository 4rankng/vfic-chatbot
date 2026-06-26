import { CanAccess, ListBase, useRecordContext, useTranslate } from "ra-core";
import { CreateButton } from "@/components/admin/create-button";
import { DataTable } from "@/components/admin/data-table";
import { TextField } from "@/components/admin/text-field";
import { DateField } from "@/components/admin/date-field";
import { TopToolbar } from "../layout/TopToolbar";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ShieldOff } from "lucide-react";

const ROLE_LABELS: Record<string, string> = {
  admin: "Quản trị",
  recruiter: "Nhân viên",
};

// Reads the current row via useRecordContext — DataTableCell renders column
// children without cloning the record into them as a prop, so a `record` prop
// would always be undefined here.
const RoleBadge = () => {
  const record = useRecordContext();
  if (!record?.role) return null;
  return (
    <Badge variant={record.role === "admin" ? "default" : "secondary"}>
      {ROLE_LABELS[record.role as string] ?? record.role}
    </Badge>
  );
};

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

export const ProfileList = () => {
  const translate = useTranslate();
  return (
    <CanAccess resource="users" action="list" accessDenied={<AccessDenied />}>
      <ListBase perPage={25} sort={{ field: "created_at", order: "DESC" }}>
        <TopToolbar>
          <h2 className="font-display text-4xl font-extrabold tracking-wide uppercase text-foreground mr-auto">
            {translate("resources.users.name", { smart_count: 2 })}
          </h2>
          <CreateButton />
        </TopToolbar>
        <Card className="mt-4">
          <DataTable bulkActionButtons={false}>
            <DataTable.Col source="full_name" label="Họ tên">
              <TextField source="full_name" className="font-semibold" />
            </DataTable.Col>
            <DataTable.Col source="email" label="Email" />
            <DataTable.Col source="role" label="Vai trò">
              <RoleBadge />
            </DataTable.Col>
            <DataTable.Col source="created_at" label="Ngày tạo">
              <DateField source="created_at" showTime />
            </DataTable.Col>
          </DataTable>
        </Card>
      </ListBase>
    </CanAccess>
  );
};
