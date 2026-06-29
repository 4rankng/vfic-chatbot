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
import { CalendarDays, Mail, Plus, ShieldOff, UserCog } from "lucide-react";
import { Link } from "react-router";
import { UserActions } from "./UserActions";
import { UserRoleBadge, UserStatusBadge } from "./UserBadges";
import type { UserAccount } from "../types";

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

export const UserList = () => {
  const translate = useTranslate();
  const { permissions, isPending } = usePermissions();

  if (isPending) return null;
  if (permissions !== "admin") return <AccessDenied />;

  return (
    <ListBase perPage={25} sort={{ field: "created_at", order: "DESC" }}>
      <UserListContent
        title={translate("resources.users.name", { smart_count: 2 })}
      />
    </ListBase>
  );
};

const UserListContent = ({ title }: { title: string }) => (
  <div className="px-4 py-5 pb-24 md:px-0 md:py-0 md:pb-0">
    <TopToolbar className="flex-nowrap items-start gap-3">
      <div className="min-w-0 flex-1">
        <h2 className="truncate text-2xl font-bold tracking-tight md:text-xl md:font-semibold">
          {title}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground md:hidden">
          Quản lý tài khoản và quyền truy cập nội bộ.
        </p>
      </div>
      <CreateUserButton />
    </TopToolbar>
    <UserMobileList />
    <div className="mt-4 hidden md:block">
      <UserDesktopTable />
    </div>
  </div>
);

const CreateUserButton = () => {
  const createPath = useCreatePath();
  return (
    <Button asChild variant="outline" className="h-10 shrink-0 rounded-xl px-3">
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
    <DataTable.Col label="Thao tác">
      <UserActions />
    </DataTable.Col>
  </DataTable>
);

const UserMobileList = () => {
  const { data, isPending } = useListContext<UserAccount>();

  if (isPending) {
    return (
      <div className="mt-4 space-y-3 md:hidden">
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
      <Card className="mt-4 p-8 text-center md:hidden">
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
    <div className="mt-4 space-y-3 md:hidden">
      {data.map((user) => (
        <RecordContextProvider key={user.id} value={user}>
          <Card className="gap-3 overflow-hidden rounded-xl p-4">
            <div className="flex items-start gap-3">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-bold text-muted-foreground">
                {initials(user.full_name || user.email)}
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

const initials = (value: string) =>
  value
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");

const formatDate = (value: string) =>
  new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(value));
