import { useRecordContext } from "ra-core";
import { Badge } from "@/components/ui/badge";

const ROLE_LABELS: Record<string, string> = {
  admin: "Quản trị",
  recruiter: "Tuyển dụng",
};

export const UserRoleBadge = () => {
  const record = useRecordContext();
  if (!record?.role) return null;
  return (
    <Badge variant={record.role === "admin" ? "default" : "secondary"}>
      {ROLE_LABELS[record.role as string] ?? record.role}
    </Badge>
  );
};

export const UserStatusBadge = () => {
  const record = useRecordContext();
  if (!record) return null;
  return (
    <Badge variant={record.disabled ? "outline" : "secondary"}>
      {record.disabled ? "Đã vô hiệu" : "Đang hoạt động"}
    </Badge>
  );
};
