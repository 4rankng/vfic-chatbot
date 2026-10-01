import {
  useCreatePath,
  useDataProvider,
  useNotify,
  useRecordContext,
  useRefresh,
} from "ra-core";
import { useHref } from "react-router";
import { useRef, useState } from "react";
import type { Key } from "react-aria-components";
import { Dropdown } from "@/components/base/dropdown/dropdown";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import {
  Dialog,
  Modal,
  ModalOverlay,
} from "@/components/application/modals/modal";
import {
  KeyRound,
  MoreHorizontal,
  Pencil,
  Power,
  PowerOff,
  Trash2,
} from "lucide-react";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { UserAccount } from "../types";

/**
 * Row actions for one account: edit, enable/disable, password reset and a hard
 * delete.
 *
 * The menu and both dialogs are Untitled UI (React Aria) rather than Radix,
 * because this cell is rendered inside the account directory's React Aria table
 * and the two primitive runtimes must not nest. Copy, data verbs and visible
 * names are unchanged: `enableUser` / `disableUser` / `resetUserPassword` /
 * `delete("users")`, with the same Vietnamese confirmations.
 */
export const UserActions = () => {
  const record = useRecordContext<UserAccount>();
  const createPath = useCreatePath();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const notify = useNotify();
  const refresh = useRefresh();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetPending, setResetPending] = useState(false);
  const [deletePending, setDeletePending] = useState(false);
  const [togglePending, setTogglePending] = useState(false);
  const mutationPending = useRef(false);
  const [passwordError, setPasswordError] = useState<string>();
  const [confirmationError, setConfirmationError] = useState<string>();
  const [resetError, setResetError] = useState<string>();
  const passwordRef = useRef<HTMLInputElement>(null);
  const confirmationRef = useRef<HTMLInputElement>(null);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const editPath = createPath({
    resource: "users",
    type: "edit",
    id: record?.id ?? "",
  });
  const editHref = useHref(editPath);
  if (!record) return null;

  const actionLabel = `Mở thao tác cho ${record.full_name || record.email}`;

  const toggleDisabled = async () => {
    if (mutationPending.current) return;
    mutationPending.current = true;
    setTogglePending(true);
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
    } finally {
      mutationPending.current = false;
      setTogglePending(false);
    }
  };

  const hardDelete = async () => {
    if (mutationPending.current) return;
    mutationPending.current = true;
    setDeletePending(true);
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
    } finally {
      mutationPending.current = false;
      setDeletePending(false);
    }
  };

  const closeResetDialog = () => {
    setResetOpen(false);
    setPassword("");
    setConfirmPassword("");
    setPasswordError(undefined);
    setConfirmationError(undefined);
    setResetError(undefined);
  };

  const resetPassword = async () => {
    if (record.disabled || mutationPending.current) return;
    if (password.length < 8) {
      setPasswordError("Mật khẩu phải có ít nhất 8 ký tự.");
      passwordRef.current?.focus();
      return;
    }
    if (password !== confirmPassword) {
      setConfirmationError("Mật khẩu xác nhận không khớp.");
      confirmationRef.current?.focus();
      return;
    }
    mutationPending.current = true;
    setResetError(undefined);
    setResetPending(true);
    try {
      await dataProvider.resetUserPassword(record.id, { password });
      notify("Đã đặt lại mật khẩu.", { type: "success" });
      closeResetDialog();
      refresh();
    } catch (e) {
      setResetError(
        (e as Error).message || "Không thể đặt lại mật khẩu. Vui lòng thử lại.",
      );
      notify((e as Error).message, { type: "error" });
    } finally {
      mutationPending.current = false;
      setResetPending(false);
    }
  };

  const handleAction = (key: Key) => {
    if (mutationPending.current) return;
    if (key === "toggle") void toggleDisabled();
    if (key === "reset") setResetOpen(true);
    if (key === "delete") setDeleteOpen(true);
  };

  return (
    <>
      <Dropdown.Root>
        <span title={actionLabel}>
          <Button
            color="tertiary"
            size="sm"
            className="size-10"
            iconLeading={MoreHorizontal}
            aria-label={actionLabel}
            isDisabled={resetPending || deletePending || togglePending}
          />
        </span>
        <Dropdown.Popover className="uu-scope w-64">
          <Dropdown.Menu onAction={handleAction}>
            <Dropdown.Item
              id="edit"
              href={editHref}
              icon={Pencil}
              label="Sửa"
            />
            <Dropdown.Item
              id="toggle"
              icon={record.disabled ? Power : PowerOff}
              label={record.disabled ? "Kích hoạt" : "Vô hiệu hóa"}
            />
            {!record.disabled ? (
              <Dropdown.Item id="reset" icon={KeyRound} label="Đổi mật khẩu" />
            ) : null}
            <Dropdown.Separator />
            <Dropdown.Item id="delete" icon={Trash2}>
              <span className="text-error-primary">Xóa vĩnh viễn</span>
            </Dropdown.Item>
          </Dropdown.Menu>
        </Dropdown.Popover>
      </Dropdown.Root>

      <ModalOverlay
        isOpen={resetOpen}
        onOpenChange={(open) => {
          if (resetPending) return;
          if (open) setResetOpen(true);
          else closeResetDialog();
        }}
        isDismissable={!resetPending}
        isKeyboardDismissDisabled={resetPending}
        className="uu-scope"
      >
        <Modal className="w-full outline-hidden sm:max-w-md">
          <Dialog
            aria-label="Đổi mật khẩu"
            className="flex flex-col gap-4 p-5 outline-hidden"
          >
            <div className="flex flex-col gap-1">
              <h2 className="flex items-center gap-2 text-section-title font-semibold text-primary">
                <KeyRound className="size-5" aria-hidden="true" />
                Đổi mật khẩu
              </h2>
              <p className="text-body-sm text-tertiary">
                {`Đặt mật khẩu mới cho ${record.email}. Người dùng sẽ cần đăng nhập lại bằng mật khẩu mới.`}
              </p>
            </div>
            <form
              className="flex flex-col gap-4"
              onSubmit={(event) => {
                event.preventDefault();
                void resetPassword();
              }}
            >
              <Input
                ref={passwordRef}
                className="uu-scope"
                wrapperClassName="[&>button]:hidden"
                label="Mật khẩu mới"
                type="password"
                autoComplete="new-password"
                autoFocus
                value={password}
                onChange={(value) => {
                  setPassword(value);
                  setPasswordError(undefined);
                  setConfirmationError(undefined);
                }}
                isDisabled={resetPending}
                isInvalid={Boolean(passwordError)}
                hint={passwordError ?? "Ít nhất 8 ký tự."}
              />
              <Input
                ref={confirmationRef}
                className="uu-scope"
                wrapperClassName="[&>button]:hidden"
                label="Xác nhận mật khẩu"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(value) => {
                  setConfirmPassword(value);
                  setConfirmationError(undefined);
                }}
                isDisabled={resetPending}
                isInvalid={Boolean(confirmationError)}
                hint={confirmationError}
              />
              {resetError ? (
                <p role="alert" className="text-helper text-error-primary">
                  {resetError}
                </p>
              ) : null}
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  color="secondary"
                  size="md"
                  isDisabled={resetPending}
                  onClick={closeResetDialog}
                >
                  Hủy
                </Button>
                <Button
                  type="submit"
                  size="md"
                  isDisabled={resetPending}
                  isLoading={resetPending}
                  showTextWhileLoading
                >
                  {resetPending ? "Đang đặt lại…" : "Đặt mật khẩu"}
                </Button>
              </div>
            </form>
          </Dialog>
        </Modal>
      </ModalOverlay>

      <ModalOverlay
        isOpen={deleteOpen}
        onOpenChange={(open) => {
          if (!deletePending) setDeleteOpen(open);
        }}
        isDismissable={!deletePending}
        isKeyboardDismissDisabled={deletePending}
        className="uu-scope"
      >
        <Modal className="w-full outline-hidden sm:max-w-md">
          <Dialog
            aria-label="Xóa vĩnh viễn tài khoản?"
            className="flex flex-col gap-4 p-5 outline-hidden"
          >
            <div className="flex flex-col gap-1">
              <h2 className="text-section-title font-semibold text-primary">
                Xóa vĩnh viễn tài khoản?
              </h2>
              <p className="text-body-sm text-tertiary">
                {`Tài khoản ${record.email} sẽ bị xóa khỏi hệ thống. Hành động này không thể hoàn tác.`}
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                color="secondary"
                size="md"
                onClick={() => setDeleteOpen(false)}
                isDisabled={deletePending}
              >
                Hủy
              </Button>
              <Button
                type="button"
                color="primary-destructive"
                size="md"
                onClick={() => void hardDelete()}
                isDisabled={deletePending}
                isLoading={deletePending}
                showTextWhileLoading
              >
                {deletePending ? "Đang xóa…" : "Xóa vĩnh viễn"}
              </Button>
            </div>
          </Dialog>
        </Modal>
      </ModalOverlay>
    </>
  );
};
