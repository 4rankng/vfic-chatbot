import {
  ListBase,
  useListContext,
  useCreatePath,
  usePermissions,
  useTranslate,
} from "ra-core";
import { useHref } from "react-router";
import { Avatar } from "@/components/base/avatar/avatar";
import { Button } from "@/components/base/buttons/button";
import { CalendarDays, Mail, Plus, ShieldOff, UserCog } from "lucide-react";
import { UserActions } from "./UserActions";
import { UserRoleBadge, UserStatusBadge } from "./UserBadges";
import type { UserAccount } from "../types";
import "./users.css";
import {
  EmptyState,
  ListTable,
  PageHeading,
  PageShell,
  type ListTableColumn,
} from "../kit";
import { LoadingState } from "../misc/LoadingState";

type UserListProps = {
  embedded?: boolean;
};

const numberFormatter = new Intl.NumberFormat("vi-VN");

const AccessDenied = () => {
  const translate = useTranslate();
  return (
    <div className="mt-4">
      <EmptyState
        icon={<ShieldOff className="size-6" aria-hidden="true" />}
        title={translate("ra.page.access_denied", { _: "Access denied" })}
        description={translate("crm.users.access_denied_help", {
          _: "Only administrators can manage users. Ask an admin to grant you access.",
        })}
      />
    </div>
  );
};

/**
 * The account directory, on the kit's `ListTable`: one card surface, one count
 * strip, the console's column set and `UserActions` as the trailing row action
 * cell. The rows, the empty state, the loading skeleton and the pager all come
 * from the bridge, so this file only declares what a user row contains.
 */
export const UserList = ({ embedded = false }: UserListProps) => {
  const translate = useTranslate();
  const { permissions, isPending } = usePermissions();

  if (isPending) return <LoadingState label="Đang kiểm tra quyền truy cập…" />;
  if (permissions !== "admin") return <AccessDenied />;

  return (
    <ListBase
      resource="users"
      perPage={25}
      sort={{ field: "created_at", order: "DESC" }}
    >
      <UserListContent
        title={translate("resources.users.name", { smart_count: 2 })}
        embedded={embedded}
      />
    </ListBase>
  );
};

const UserListContent = ({
  title,
  embedded,
}: {
  title: string;
  embedded: boolean;
}) =>
  embedded ? (
    <div className="settings-embedded-users-list">
      <header className="user-directory-toolbar">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-section-title font-semibold tracking-tight">
            {title}
          </h2>
          <p className="mt-1 text-body-sm text-muted-foreground">
            Quản lý tài khoản và quyền truy cập nội bộ.
          </p>
        </div>
        <CreateUserButton />
      </header>
      <UserAccountTable />
    </div>
  ) : (
    <PageShell size="wide">
      <PageHeading
        eyebrow="Quản trị truy cập"
        title={title}
        subtitle="Tài khoản và quyền truy cập nội bộ."
        actions={<CreateUserButton />}
      />
      <UserAccountTable className="mt-4" />
    </PageShell>
  );

const CreateUserButton = () => {
  const createPath = useCreatePath();
  const href = useHref(createPath({ resource: "users", type: "create" }));
  return (
    <Button
      href={href}
      size="sm"
      className="user-directory-create shrink-0"
      iconLeading={Plus}
    >
      Tạo tài khoản
    </Button>
  );
};

/** The muted count line that opens the table surface. */
const UserAccountCount = () => {
  const { total, isPending } = useListContext<UserAccount>();
  return (
    <header className="user-directory-header flex items-center justify-between gap-3 border-b border-secondary px-3 py-2.5">
      <p className="text-body-sm font-medium tabular-nums text-tertiary">
        {isPending
          ? "Đang tải tài khoản…"
          : `${numberFormatter.format(total ?? 0)} tài khoản`}
      </p>
    </header>
  );
};

const USER_COLUMNS: ListTableColumn<UserAccount>[] = [
  {
    id: "avatar",
    header: <span className="sr-only">Ảnh đại diện</span>,
    headClassName: "w-16",
    cellClassName: "user-directory-cell-avatar",
    // Untitled UI v8 Avatar: initials, with the library's own placeholder as the
    // fallback. It uses only `text-fg-quaternary`, none of the four names the
    // console and the library both define, so it needs no scope of its own.
    cell: (user) => (
      <Avatar
        size="md"
        alt={user.full_name || user.email}
        initials={initialsOf(user)}
      />
    ),
  },
  {
    id: "name",
    header: "Người dùng",
    isRowHeader: true,
    cellClassName: "user-directory-cell-identity",
    cell: (user) => (
      <div className="user-directory-identity">
        <h3>{user.full_name || "Chưa có tên"}</h3>
        <p>
          <Mail className="size-3.5" aria-hidden="true" />
          <span>{user.email}</span>
        </p>
      </div>
    ),
  },
  {
    id: "role",
    header: "Vai trò",
    headClassName: "w-40",
    cellClassName: "user-directory-cell-role",
    cell: () => (
      <div className="user-directory-role">
        <UserRoleBadge />
      </div>
    ),
  },
  {
    id: "status",
    header: "Trạng thái",
    headClassName: "w-36",
    cellClassName: "user-directory-cell-status",
    cell: () => (
      <div className="user-directory-status">
        <UserStatusBadge />
      </div>
    ),
  },
  {
    id: "created",
    header: "Ngày tạo",
    headClassName: "w-36",
    cellClassName: "user-directory-cell-created",
    cell: (user) => (
      <p className="user-directory-created">
        <CalendarDays className="size-3.5" aria-hidden="true" />
        <span>{formatDate(user.created_at)}</span>
      </p>
    ),
  },
];

const UserAccountTable = ({ className }: { className?: string }) => (
  <ListTable<UserAccount>
    className={className}
    ariaLabel="Danh sách tài khoản"
    columns={USER_COLUMNS}
    rowActions={() => <UserActions />}
    header={<UserAccountCount />}
    classNames={{
      table: "user-directory-table w-full table-fixed border-collapse",
      head: "user-directory-head",
      body: "user-directory-body",
      row: "user-directory-row even:bg-[var(--workspace-surface-muted)]",
      actionsCell: "user-directory-cell-actions",
    }}
    empty={{
      icon: <UserCog className="size-6" aria-hidden="true" />,
      title: "Chưa có tài khoản nào",
      description: "Tạo tài khoản để phân quyền cho đội tuyển dụng.",
    }}
  />
);

/**
 * Two-letter initials for the directory avatar. Vietnamese names put the family
 * name first, so the first and last words carry the identity ("Nguyễn Văn An" ->
 * NA); a single word yields one letter, and a missing name falls back to the
 * email so the avatar is never blank.
 */
const initialsOf = (user: UserAccount) => {
  const source = user.full_name.trim() || user.email.trim();
  const words = source.split(/\s+/).filter(Boolean);
  const first = words.at(0)?.charAt(0) ?? "";
  const last = words.length > 1 ? (words.at(-1)?.charAt(0) ?? "") : "";

  return `${first}${last}`.toUpperCase();
};

const formatDate = (value: string) =>
  new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(value));
