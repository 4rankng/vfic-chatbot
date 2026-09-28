import {
  ListBase,
  RecordContextProvider,
  useCreatePath,
  useListContext,
  usePermissions,
  useTranslate,
} from "ra-core";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  CalendarDays,
  Mail,
  Plus,
  ShieldOff,
  UserCog,
  UserRound,
} from "lucide-react";
import { Link } from "react-router";
import { UserActions } from "./UserActions";
import { UserRoleBadge, UserStatusBadge } from "./UserBadges";
import type { UserAccount } from "../types";
import "./users.css";
import { EmptyState, PageHeading, PageShell } from "../kit";

type UserListProps = {
  embedded?: boolean;
};

/**
 * Tailkit `a-c-tables-08` column headings at console density: a 13px uppercase
 * caption on the muted strip. The strip colour sits on the cells (the catalog
 * paints `thead` cells, not the row group) and the table wrapper already draws
 * the hairline row separators and the horizontal scroll container.
 */
const COLUMN_HEADING =
  "bg-[var(--tt-surface-muted)] px-3 text-left text-[length:var(--text-caption)] font-semibold uppercase tracking-[0.05em] text-[var(--tt-ink-muted)]";

const numberFormatter = new Intl.NumberFormat("vi-VN");

const AccessDenied = () => {
  const translate = useTranslate();
  return (
    <Card className="mt-4">
      <div className="flex flex-col items-center gap-3 p-10 text-center text-muted-foreground">
        <ShieldOff className="size-10 opacity-60" />
        <p className="text-section-title font-medium text-foreground">
          {translate("ra.page.access_denied", { _: "Access denied" })}
        </p>
        <p className="max-w-sm text-body">
          {translate("crm.users.access_denied_help", {
            _: "Only administrators can manage users. Ask an admin to grant you access.",
          })}
        </p>
      </div>
    </Card>
  );
};

export const UserList = ({ embedded = false }: UserListProps) => {
  const translate = useTranslate();
  const { permissions, isPending } = usePermissions();

  if (isPending) return null;
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
          <h2 className="truncate text-content-title font-semibold tracking-tight">
            {title}
          </h2>
          <p className="mt-1 text-body-sm text-muted-foreground">
            Quản lý tài khoản và quyền truy cập nội bộ.
          </p>
        </div>
        <CreateUserButton />
      </header>
      <UserAccountList />
    </div>
  ) : (
    <PageShell size="wide">
      <PageHeading
        eyebrow="Quản trị truy cập"
        title={title}
        subtitle="Tài khoản và quyền truy cập nội bộ."
        actions={<CreateUserButton />}
      />
      <div className="mt-4">
        <UserAccountList />
      </div>
    </PageShell>
  );

const CreateUserButton = () => {
  const createPath = useCreatePath();
  return (
    <Button asChild size="sm" className="user-directory-create shrink-0">
      <Link to={createPath({ resource: "users", type: "create" })}>
        <Plus className="size-4" />
        <span>Tạo tài khoản</span>
      </Link>
    </Button>
  );
};

const UserAccountList = () => {
  const { data, isPending } = useListContext<UserAccount>();

  if (isPending) {
    return (
      <section
        className="user-directory-card overflow-hidden rounded-sm border border-[var(--tt-border)] bg-[var(--tt-surface-lift)]"
        aria-busy="true"
      >
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="user-directory-skeleton">
            <Skeleton className="size-9 rounded-full" />
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-4 w-40 max-w-full" />
              <Skeleton className="h-3 w-56 max-w-full" />
            </div>
            <Skeleton className="h-6 w-24 rounded-full" />
          </div>
        ))}
      </section>
    );
  }

  if (!data || data.length === 0) {
    return (
      <EmptyState
        className="mt-4"
        icon={<UserCog className="size-6" aria-hidden="true" />}
        title="Chưa có tài khoản nào"
        description="Tạo tài khoản để phân quyền cho đội tuyển dụng."
      />
    );
  }

  return (
    <section className="user-directory-card overflow-hidden rounded-sm border border-[var(--tt-border)] bg-[var(--tt-surface-lift)]">
      {/* `a-c-tables-08` header block: the muted count line that opens the
          table surface. The surface title itself is rendered above by the page
          heading (standalone route) or the embedded directory toolbar. */}
      <header className="user-directory-header flex items-center justify-between gap-3 border-b border-[var(--tt-border)] px-3 py-2.5">
        <p className="text-[length:var(--text-body-sm)] font-medium tabular-nums text-[var(--tt-ink-muted)]">
          {numberFormatter.format(data.length)} tài khoản
        </p>
      </header>
      <div className="overflow-x-auto">
        <table
          className="user-directory-table w-full table-fixed border-collapse"
          aria-label="Danh sách tài khoản"
        >
          <thead className="user-directory-head">
            <tr>
              <th scope="col" className={`w-16 ${COLUMN_HEADING}`}>
                <span className="sr-only">Ảnh đại diện</span>
              </th>
              <th scope="col" className={COLUMN_HEADING}>
                Người dùng
              </th>
              <th scope="col" className={`w-40 ${COLUMN_HEADING}`}>
                Vai trò
              </th>
              <th scope="col" className={`w-36 ${COLUMN_HEADING}`}>
                Trạng thái
              </th>
              <th scope="col" className={`w-36 ${COLUMN_HEADING}`}>
                Ngày tạo
              </th>
              <th scope="col" className={`w-20 ${COLUMN_HEADING}`}>
                <span className="sr-only">Thao tác</span>
              </th>
            </tr>
          </thead>
          <tbody className="user-directory-body">
            {data.map((user) => (
              <RecordContextProvider key={user.id} value={user}>
                {/* Row hover is the kit's `tbody tr:hover` accent tint. */}
                <tr className="user-directory-row border-b border-[var(--tt-border)] last:border-b-0 even:bg-[var(--tt-surface-muted)]">
                  <td className="user-directory-cell-avatar p-3 align-middle">
                    <div className="tt-avatar tt-avatar-placeholder user-directory-avatar">
                      <div>
                        <UserRound className="size-4" aria-hidden="true" />
                      </div>
                    </div>
                  </td>
                  <td className="user-directory-cell-identity p-3 align-middle">
                    <div className="user-directory-identity">
                      <h3>{user.full_name || "Chưa có tên"}</h3>
                      <p>
                        <Mail className="size-3.5" aria-hidden="true" />
                        <span>{user.email}</span>
                      </p>
                    </div>
                  </td>
                  <td className="user-directory-cell-role p-3 align-middle">
                    <div className="user-directory-role">
                      <UserRoleBadge />
                    </div>
                  </td>
                  <td className="user-directory-cell-status p-3 align-middle">
                    <div className="user-directory-status">
                      <UserStatusBadge />
                    </div>
                  </td>
                  <td className="user-directory-cell-created p-3 align-middle">
                    <p className="user-directory-created">
                      <CalendarDays className="size-3.5" aria-hidden="true" />
                      <span>{formatDate(user.created_at)}</span>
                    </p>
                  </td>
                  <td className="user-directory-cell-actions p-3 align-middle">
                    <div className="user-directory-actions">
                      <UserActions />
                    </div>
                  </td>
                </tr>
              </RecordContextProvider>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
};

const formatDate = (value: string) =>
  new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(value));
