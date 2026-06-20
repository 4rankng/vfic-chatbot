import { ListBase, useTranslate } from "ra-core";
import { CreateButton } from "@/components/admin/create-button";
import { DataTable } from "@/components/admin/data-table";
import { TextField } from "@/components/admin/text-field";
import { DateField } from "@/components/admin/date-field";
import { TopToolbar } from "../layout/TopToolbar";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const RoleBadge = ({ record }: any) => {
  if (!record) return null;
  return (
    <Badge variant={record.role === "admin" ? "default" : "secondary"}>
      {record.role}
    </Badge>
  );
};

export const ProfileList = () => {
  const translate = useTranslate();
  return (
    <ListBase perPage={25} sort={{ field: "created_at", order: "DESC" }}>
      <TopToolbar>
        <h2 className="text-xl font-semibold mr-auto">{translate("resources.profiles.name", { smart_count: 2 })}</h2>
        <CreateButton />
      </TopToolbar>
      <Card className="mt-4">
        <DataTable bulkActionButtons={false}>
          <DataTable.Col source="full_name" label="Name">
            <TextField source="full_name" className="font-semibold" />
          </DataTable.Col>
          <DataTable.Col source="email" label="Email" />
          <DataTable.Col source="role" label="Role">
            <RoleBadge source="role" label="Role" />
          </DataTable.Col>
          <DataTable.Col source="created_at" label="Created At">
            <DateField source="created_at" showTime />
          </DataTable.Col>
        </DataTable>
      </Card>
    </ListBase>
  );
};
