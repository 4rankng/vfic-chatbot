import { List } from "@/components/admin/list";
import { DataTable } from "@/components/admin/data-table";
import { TextField } from "@/components/admin/text-field";
import { DateField } from "@/components/admin/date-field";
import { useRecordContext } from "ra-core";

const LIFECYCLE_LABELS: Record<string, string> = {
  OPEN: "Đang mở",
  CLOSED: "Đã đóng",
  CANCELLED: "Đã huỷ",
};

export const formatCaseLifecycle = (lifecycle?: string): string =>
  lifecycle ? (LIFECYCLE_LABELS[lifecycle] ?? "Không xác định") : "Không xác định";

const LifecycleField = () => {
  const record = useRecordContext<{ lifecycle?: string }>();
  return <span>{formatCaseLifecycle(record?.lifecycle)}</span>;
};

export const CaseList = () => (
  <List title="Hồ sơ công việc" perPage={25} sort={{ field: "updated_at", order: "DESC" }}>
    <DataTable bulkActionButtons={false}>
      <DataTable.Col source="case_no" label="Mã hồ sơ" />
      <DataTable.Col source="subject" label="Tiêu đề">
        <TextField source="subject" className="font-semibold" />
      </DataTable.Col>
      <DataTable.Col source="stage_key" label="Giai đoạn" />
      <DataTable.Col source="lifecycle" label="Trạng thái">
        <LifecycleField />
      </DataTable.Col>
      <DataTable.Col source="updated_at" label="Cập nhật">
        <DateField source="updated_at" showTime />
      </DataTable.Col>
    </DataTable>
  </List>
);
