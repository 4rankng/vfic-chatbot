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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  KeyRound,
  MoreHorizontal,
  Pencil,
  Power,
  PowerOff,
  Trash2,
} from "lucide-react";
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
  const [resetOpen, setResetOpen] = useState(false);
  const [resetPending, setResetPending] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
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

  const closeResetDialog = () => {
    setResetOpen(false);
    setPassword("");
    setConfirmPassword("");
  };

  const resetPassword = async () => {
    if (record.disabled || resetPending) return;
    if (password.length < 8) {
      notify("Mật khẩu phải có ít nhất 8 ký tự.", { type: "error" });
      return;
    }
    if (password !== confirmPassword) {
      notify("Mật khẩu xác nhận không khớp.", { type: "error" });
      return;
    }
    setResetPending(true);
    try {
      await dataProvider.resetUserPassword(record.id, { password });
      notify("Đã đặt lại mật khẩu.", { type: "success" });
      closeResetDialog();
      refresh();
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
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
                Đổi mật khẩu
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
      <Dialog
        open={resetOpen}
        onOpenChange={(open) => {
          if (!resetPending) {
            if (open) setResetOpen(true);
            else closeResetDialog();
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <KeyRound className="size-5" />
              Đổi mật khẩu
            </DialogTitle>
            <DialogDescription>
              Đặt mật khẩu mới cho {record.email}. Người dùng sẽ cần đăng nhập
              lại bằng mật khẩu mới.
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void resetPassword();
            }}
            className="flex flex-col gap-4"
          >
            <div className="flex flex-col gap-2">
              <Label htmlFor="reset-password-new">Mật khẩu mới</Label>
              <Input
                id="reset-password-new"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={8}
                required
                autoFocus
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="reset-password-confirm">Xác nhận mật khẩu</Label>
              <Input
                id="reset-password-confirm"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                minLength={8}
                required
              />
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={resetPending}
                onClick={closeResetDialog}
              >
                Hủy
              </Button>
              <Button type="submit" disabled={resetPending}>
                {resetPending ? "Đang đặt lại…" : "Đặt mật khẩu"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
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
