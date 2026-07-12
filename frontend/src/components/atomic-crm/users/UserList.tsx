import {
  ListBase,
  RecordContextProvider,
  useCreatePath,
  useListContext,
  usePermissions,
  useTranslate,
} from "ra-core";
import { DataTable } from "@/components/admin/data-table";
import { TextField } from "@/components/admin/text-field";
import { DateField } from "@/components/admin/date-field";
import { TopToolbar } from "../layout/TopToolbar";
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

type UserListProps = {
  embedded?: boolean;
};

const AccessDenied = () => {
  const translate = useTranslate();
  return (
    <Card className="mt-4">
      <div className="flex flex-col items-center gap-3 p-10 text-center text-muted-foreground">
        <ShieldOff className="size-10 opacity-60" />
        <p className="text-base font-medium text-foreground">
          {translate("ra.page.access_denied", { _: "Access denied" })}
        </p>
        <p className="max-w-sm text-sm">
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
}) => (
  <div
    className={
      embedded
        ? "settings-embedded-users-list"
        : "mx-auto w-full max-w-[1440px] px-4 py-5 pb-24 md:px-6 md:py-6 md:pb-6 lg:px-8"
    }
  >
    <TopToolbar className="flex-nowrap items-start gap-3">
      <div className="min-w-0 flex-1">
        <h2 className="truncate text-page-title font-bold tracking-tight">
          {title}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground lg:hidden">
          Quản lý tài khoản và quyền truy cập nội bộ.
        </p>
      </div>
      <CreateUserButton />
    </TopToolbar>
    <UserMobileList />
    <div className="mt-4 hidden lg:block">
      <UserDesktopTable />
    </div>
  </div>
);

const CreateUserButton = () => {
  const createPath = useCreatePath();
  return (
    <Button asChild variant="outline" className="h-11 shrink-0 rounded-xl px-3">
      <Link to={createPath({ resource: "users", type: "create" })}>
        <Plus className="size-4" />
        <span className="hidden min-[360px]:inline">Tạo</span>
      </Link>
    </Button>
  );
};

const UserDesktopTable = () => (
  <DataTable bulkActionButtons={false}>
    <DataTable.Col source="full_name" label="Họ tên">
      <TextField source="full_name" className="font-semibold" />
    </DataTable.Col>
    <DataTable.Col source="email" label="Email" />
    <DataTable.Col source="role" label="Vai trò">
      <UserRoleBadge />
    </DataTable.Col>
    <DataTable.Col source="disabled" label="Trạng thái">
      <UserStatusBadge />
    </DataTable.Col>
    <DataTable.Col source="created_at" label="Ngày tạo">
      <DateField source="created_at" showTime />
    </DataTable.Col>
    <DataTable.Col
      label="Thao tác"
      disableSort
      className="w-20 min-w-20 text-right"
    >
      <UserActions />
    </DataTable.Col>
  </DataTable>
);

const UserMobileList = () => {
  const { data, isPending } = useListContext<UserAccount>();

  if (isPending) {
    return (
      <div className="mt-4 space-y-3 lg:hidden">
        {Array.from({ length: 4 }).map((_, index) => (
          <Card key={index} className="gap-3 p-4">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-4 w-56" />
            <div className="flex gap-2">
              <Skeleton className="h-7 w-20 rounded-full" />
              <Skeleton className="h-7 w-28 rounded-full" />
            </div>
          </Card>
        ))}
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <Card role="status" className="mt-4 p-8 text-center lg:hidden">
        <div className="mx-auto mb-3 flex size-10 items-center justify-center rounded-full bg-muted">
          <UserCog className="size-5 text-muted-foreground" />
        </div>
        <p className="text-sm font-medium">Chưa có tài khoản nào</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Tạo tài khoản để phân quyền cho đội tuyển dụng.
        </p>
      </Card>
    );
  }

  return (
    <div className="mt-4 space-y-3 lg:hidden">
      {data.map((user) => (
        <RecordContextProvider key={user.id} value={user}>
          <Card className="gap-3 overflow-hidden rounded-xl p-4">
            <div className="flex items-start gap-3">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-bold text-muted-foreground">
                <UserRound className="size-5" aria-hidden="true" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-start gap-2">
                  <h3 className="min-w-0 flex-1 truncate text-base font-semibold leading-6">
                    {user.full_name || "Chưa có tên"}
                  </h3>
                  <UserActions />
                </div>
                <p className="mt-0.5 flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground">
                  <Mail className="size-3.5 shrink-0" />
                  <span className="truncate">{user.email}</span>
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2 pl-13">
              <UserRoleBadge />
              <UserStatusBadge />
            </div>
            <p className="flex items-center gap-1.5 pl-13 text-xs text-muted-foreground">
              <CalendarDays className="size-3.5" />
              Tạo {formatDate(user.created_at)}
            </p>
          </Card>
        </RecordContextProvider>
      ))}
    </div>
  );
};

const formatDate = (value: string) =>
  new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(value));
