import { List } from "@/components/admin/list";
import { DataTable } from "@/components/admin/data-table";
import { TextField } from "@/components/admin/text-field";
import { DateField } from "@/components/admin/date-field";

export const ContactList = () => (
  <List title="Liên hệ" perPage={25} sort={{ field: "updated_at", order: "DESC" }}>
    <DataTable bulkActionButtons={false}>
      <DataTable.Col source="display_name" label="Tên hiển thị">
        <TextField source="display_name" className="font-semibold" />
      </DataTable.Col>
      <DataTable.Col source="primary_phone" label="Điện thoại" />
      <DataTable.Col source="primary_email" label="Email" />
      <DataTable.Col source="locale" label="Ngôn ngữ" />
      <DataTable.Col source="updated_at" label="Cập nhật">
        <DateField source="updated_at" showTime />
      </DataTable.Col>
    </DataTable>
  </List>
);
