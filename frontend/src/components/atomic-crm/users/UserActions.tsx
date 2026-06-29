import { useDataProvider, useNotify, useRecordContext, useRefresh } from "ra-core";
import { EditButton } from "@/components/admin/edit-button";
import { Button } from "@/components/ui/button";
import { Power, PowerOff } from "lucide-react";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { UserAccount } from "../types";

export const UserActions = () => {
  const record = useRecordContext<UserAccount>();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const notify = useNotify();
  const refresh = useRefresh();
  if (!record) return null;

  const toggleDisabled = async () => {
    try {
      if (record.disabled) {
        await dataProvider.enableUser(record.id);
        notify("Đã kích hoạt tài khoản.", { type: "success" });
      } else {
        await dataProvider.disableUser(record.id);
        notify("Đã vô hiệu hóa tài khoản.", { type: "success" });
      }
      refresh();
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    }
  };

  return (
    <div className="flex flex-wrap gap-2">
      <EditButton label="Sửa" />
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={toggleDisabled}
        title={record.disabled ? "Kích hoạt tài khoản" : "Vô hiệu hóa tài khoản"}
      >
        {record.disabled ? <Power className="size-4" /> : <PowerOff className="size-4" />}
        {record.disabled ? "Kích hoạt" : "Vô hiệu"}
      </Button>
    </div>
  );
};
