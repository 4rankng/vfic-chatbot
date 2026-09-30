import { useCallback } from "react";
import { useHref } from "react-router";
import type { Key } from "react-aria-components";
import {
  useAuthProvider,
  useGetIdentity,
  useLogout,
  useTranslate,
} from "ra-core";
import { LogOut, Settings, UserRound } from "lucide-react";

import { Avatar } from "@/components/base/avatar/avatar";
import { Button } from "@/components/base/buttons/button";
import { Dropdown } from "@/components/base/dropdown/dropdown";
import { useRoleActions } from "../../hooks/useRoleActions";

export type AccountMenuProps = {
  /** Trigger shape: a labelled topbar button or the drawer account card. */
  variant?: "topbar" | "sidebar";
};

/**
 * Signed-in account menu. Same menu in both shells: the topbar renders an
 * avatar button, the sidebar renders a full-width account card. Navigation
 * items are real anchors built with the router's `useHref`, so the hash router
 * keeps middle-click and "open in new tab" working.
 */
export const AccountMenu = ({ variant = "topbar" }: AccountMenuProps) => {
  const authProvider = useAuthProvider();
  const { data: identity } = useGetIdentity();
  const logout = useLogout();
  const translate = useTranslate();
  const { isAdmin } = useRoleActions();
  const profileHref = useHref("/profile");
  const usersHref = useHref("/users");

  const handleAction = useCallback(
    (key: Key) => {
      if (key === "logout") {
        void logout();
      }
    },
    [logout],
  );

  if (!authProvider) return null;

  const displayName = identity?.fullName?.trim() || "Tài khoản";
  const email = identity?.email?.trim() ?? "";
  const avatarSrc = identity?.avatar?.trim();

  const trigger =
    variant === "sidebar" ? (
      <Button
        color="tertiary"
        aria-label="Mở menu tài khoản"
        className="w-full justify-start"
        size="md"
      >
        <span className="flex min-w-0 items-center gap-3">
          <Avatar
            size="sm"
            src={avatarSrc}
            alt={displayName}
            initials={displayName.slice(0, 1).toUpperCase()}
          />
          <span className="flex min-w-0 flex-col items-start">
            <span className="truncate text-sm font-semibold text-primary">
              {displayName}
            </span>
            {email ? (
              <span className="truncate text-xs text-tertiary">{email}</span>
            ) : null}
          </span>
        </span>
      </Button>
    ) : (
      <Button
        color="tertiary"
        aria-label="Mở menu tài khoản"
        className="rounded-lg"
        size="md"
      >
        <span className="flex items-center gap-2">
          <Avatar
            size="xs"
            src={avatarSrc}
            alt={displayName}
            initials={displayName.slice(0, 1).toUpperCase()}
          />
          <span className="hidden max-w-40 truncate text-sm font-semibold text-secondary md:inline">
            {displayName}
          </span>
        </span>
      </Button>
    );

  return (
    <Dropdown.Root>
      {trigger}
      <Dropdown.Popover placement="bottom end" className="w-60">
        <Dropdown.Menu onAction={handleAction}>
          <Dropdown.Item
            id="profile"
            href={profileHref}
            icon={UserRound}
            label={translate("crm.profile.title", { _: "Hồ sơ cá nhân" })}
          />
          {isAdmin ? (
            <Dropdown.Item
              id="users"
              href={usersHref}
              icon={Settings}
              label="Người dùng"
            />
          ) : null}
          <Dropdown.Separator />
          <Dropdown.Item
            id="logout"
            icon={LogOut}
            label={translate("ra.auth.logout", { _: "Đăng xuất" })}
          />
        </Dropdown.Menu>
      </Dropdown.Popover>
    </Dropdown.Root>
  );
};
