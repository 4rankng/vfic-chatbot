import {
  useCreatePath,
  useDataProvider,
  useNotify,
  useRecordContext,
  useRefresh,
} from "ra-core";
import { Button } from "@/components/ui/button";
import { Confirm } from "@/components/admin/confirm";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { MoreHorizontal, Pencil, Power, PowerOff, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { UserAccount } from "../types";

export const UserActions = () => {
  const record = useRecordContext<UserAccount>();
  const createPath = useCreatePath();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const notify = useNotify();
  const refresh = useRefresh();
  const [deleteOpen, setDeleteOpen] = useState(false);
  if (!record) return null;

  const editPath = createPath({
    resource: "users",
    type: "edit",
    id: record.id,
  });

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

  const hardDelete = async () => {
    try {
      await dataProvider.delete("users", {
        id: record.id,
        previousData: record,
      });
      notify("Đã xóa vĩnh viễn tài khoản.", { type: "success" });
      setDeleteOpen(false);
      refresh();
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    }
  };

  return (
    <>
      <div
        className="inline-flex"
        onClick={(event) => event.stopPropagation()}
        onPointerDown={(event) => event.stopPropagation()}
      >
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              title="Thao tác"
            >
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="end"
            className="w-44"
            onClick={(event) => event.stopPropagation()}
            onPointerDown={(event) => event.stopPropagation()}
          >
            <DropdownMenuItem asChild>
              <Link
                to={editPath}
                className="flex items-center gap-2"
                onClick={(event) => event.stopPropagation()}
              >
                <Pencil className="size-4" />
                Sửa
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={(event) => {
                event.stopPropagation();
                void toggleDisabled();
              }}
            >
              {record.disabled ? (
                <Power className="size-4" />
              ) : (
                <PowerOff className="size-4" />
              )}
              {record.disabled ? "Kích hoạt" : "Vô hiệu hóa"}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              variant="destructive"
              onSelect={(event) => {
                event.preventDefault();
                event.stopPropagation();
                setDeleteOpen(true);
              }}
            >
              <Trash2 className="size-4" />
              Xóa vĩnh viễn
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <Confirm
        isOpen={deleteOpen}
        title="Xóa vĩnh viễn tài khoản?"
        content={`Tài khoản ${record.email} sẽ bị xóa khỏi hệ thống. Hành động này không thể hoàn tác.`}
        confirm="Xóa vĩnh viễn"
        confirmColor="warning"
        onClose={() => setDeleteOpen(false)}
        onConfirm={hardDelete}
      />
    </>
  );
};
