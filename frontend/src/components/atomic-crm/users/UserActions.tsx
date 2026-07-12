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
import {
  KeyRound,
  MoreHorizontal,
  Pencil,
  Power,
  PowerOff,
  Trash2,
} from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router";
import { requestPasswordResetOtp } from "../login/passwordRecoveryService";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { UserAccount } from "../types";

export const UserActions = () => {
  const record = useRecordContext<UserAccount>();
  const createPath = useCreatePath();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const notify = useNotify();
  const refresh = useRefresh();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetPending, setResetPending] = useState(false);
  const resetPendingRef = useRef(false);
  if (!record) return null;

  const editPath = createPath({
    resource: "users",
    type: "edit",
    id: record.id,
  });
  const actionLabel = `Mở thao tác cho ${record.full_name || record.email}`;

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

  const requestPasswordReset = async () => {
    if (record.disabled || resetPendingRef.current) return;
    resetPendingRef.current = true;
    setResetPending(true);
    try {
      await requestPasswordResetOtp(record.email);
      notify("Nếu tài khoản đủ điều kiện, email đặt lại mật khẩu sẽ được gửi.", {
        type: "success",
      });
      setResetOpen(false);
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      resetPendingRef.current = false;
      setResetPending(false);
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
              className="h-11 w-11 rounded-full"
              aria-label={actionLabel}
              title={actionLabel}
            >
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="end"
            className="w-64"
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
            {!record.disabled ? (
              <DropdownMenuItem
                onSelect={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  setResetOpen(true);
                }}
              >
                <KeyRound className="size-4" />
                Gửi email đặt lại mật khẩu
              </DropdownMenuItem>
            ) : null}
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
        isOpen={resetOpen}
        loading={resetPending}
        title="Gửi email đặt lại mật khẩu?"
        content={`Hệ thống sẽ gửi mã xác thực đặt lại mật khẩu đến ${record.email}. Quản trị viên không thể xem hoặc đặt mật khẩu của tài khoản này.`}
        confirm={resetPending ? "Đang gửi…" : "Gửi email"}
        ConfirmIcon={KeyRound}
        onClose={() => {
          if (!resetPending) setResetOpen(false);
        }}
        onConfirm={() => void requestPasswordReset()}
      />
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
