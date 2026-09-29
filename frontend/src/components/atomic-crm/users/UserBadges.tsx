import { useRecordContext } from "ra-core";
import { Badge } from "@/components/base/badges/badges";

const ROLE_LABELS: Record<string, string> = {
  admin: "Quản trị",
  recruiter: "Tuyển dụng",
};

/**
 * The account's role and status chips, on Untitled UI's `Badge`.
 *
 * `uu-scope` is required: the chip is rendered inside the account directory's
 * React Aria table, and the wrapper re-binds the four utility names this console
 * and Untitled UI both define. See `src/styles/untitledui-theme.css`.
 */
export const UserRoleBadge = () => {
  const record = useRecordContext();
  if (!record?.role) return null;
  return (
    <Badge
      className="uu-scope"
      type="pill-color"
      size="sm"
      color={record.role === "admin" ? "brand" : "gray"}
    >
      {ROLE_LABELS[record.role as string] ?? record.role}
    </Badge>
  );
};

export const UserStatusBadge = () => {
  const record = useRecordContext();
  if (!record) return null;
  return (
    <Badge
      className="uu-scope"
      type="pill-color"
      size="sm"
      color={record.disabled ? "error" : "success"}
    >
      {record.disabled ? "Vô hiệu" : "Hoạt động"}
    </Badge>
  );
};
