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

type UserListProps = {
  embedded?: boolean;
};

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
}) => (
  <div
    className={
      embedded
        ? "settings-embedded-users-list"
        : "mx-auto w-full max-w-[1440px] px-4 py-5 pb-24 md:px-6 md:py-6 md:pb-6 lg:px-8"
    }
  >
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
      <div className="tt-card tt-card-border user-directory-card" aria-busy="true">
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
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <Card role="status" className="user-directory-empty mt-4 p-8 text-center">
        <div className="mx-auto mb-3 flex size-10 items-center justify-center rounded-full bg-muted">
          <UserCog className="size-5 text-muted-foreground" />
        </div>
        <p className="text-body font-medium">Chưa có tài khoản nào</p>
        <p className="mt-1 text-helper text-muted-foreground">
          Tạo tài khoản để phân quyền cho đội tuyển dụng.
        </p>
      </Card>
    );
  }

  return (
    <section className="tt-card tt-card-border user-directory-card">
      <div className="user-directory-columns" aria-hidden="true">
        <span />
        <span>Người dùng</span>
        <span>Vai trò</span>
        <span>Trạng thái</span>
        <span>Ngày tạo</span>
        <span />
      </div>
      <ul className="tt-list user-directory-list">
        {data.map((user) => (
          <RecordContextProvider key={user.id} value={user}>
            <li className="tt-list-row user-directory-row">
              <div className="tt-avatar tt-avatar-placeholder user-directory-avatar">
                <div>
                  <UserRound className="size-4" aria-hidden="true" />
                </div>
              </div>
              <div className="user-directory-identity">
                <h3>{user.full_name || "Chưa có tên"}</h3>
                <p>
                  <Mail className="size-3.5" aria-hidden="true" />
                  <span>{user.email}</span>
                </p>
              </div>
              <div className="user-directory-meta">
                <div className="user-directory-role">
                  <UserRoleBadge />
                </div>
                <div className="user-directory-status">
                  <UserStatusBadge />
                </div>
                <p className="user-directory-created">
                  <CalendarDays className="size-3.5" aria-hidden="true" />
                  <span>{formatDate(user.created_at)}</span>
                </p>
              </div>
              <div className="user-directory-actions">
                <UserActions />
              </div>
            </li>
          </RecordContextProvider>
        ))}
      </ul>
    </section>
  );
};

const formatDate = (value: string) =>
  new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(value));
