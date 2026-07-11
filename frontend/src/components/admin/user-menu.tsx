import { useCallback, useState } from "react";
import {
  useAuthProvider,
  useGetIdentity,
  useLogout,
  useTranslate,
  UserMenuContext,
} from "ra-core";
import { LogOut, User } from "lucide-react";
import { Link } from "react-router";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type UserMenuProps = {
  variant?: "icon" | "topbar";
};

/**
 * User menu shown in the top-right of the admin layout. Surfaces the signed-in
 * user's avatar/name and links to their own profile, the users admin (admin
 * only), and logout. Profile/Users items render only on desktop layouts — the
 * matching routes are themselves desktop-gated in CRM.tsx.
 */
export function UserMenu({ variant = "icon" }: UserMenuProps) {
  const authProvider = useAuthProvider();
  const { data: identity } = useGetIdentity();
  const logout = useLogout();
  const translate = useTranslate();

  const [open, setOpen] = useState(false);

  const handleToggleOpen = useCallback(() => {
    setOpen((prevOpen) => !prevOpen);
  }, []);

  const handleClose = useCallback(() => {
    setOpen(false);
  }, []);

  if (!authProvider) return null;

  return (
    <UserMenuContext.Provider value={{ onClose: handleClose }}>
      <DropdownMenu open={open} onOpenChange={handleToggleOpen}>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size={variant === "topbar" ? "default" : "icon"}
            aria-label="Mở menu tài khoản"
            className={cn(
              "workspace-user-menu-trigger",
              variant === "topbar" && "workspace-user-menu-trigger--labeled",
            )}
          >
            {identity?.avatar ? (
              <img
                src={identity.avatar}
                className="h-5 w-5 rounded-full object-cover"
                alt={translate("crm.profile.title", { _: "Profile" })}
              />
            ) : (
              <User className="h-5 w-5" />
            )}
            {variant === "topbar" ? (
              <span className="workspace-user-menu-name">
                {identity?.fullName ?? "Tài khoản"}
              </span>
            ) : null}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-40" align="end" forceMount>
          <DropdownMenuItem asChild>
            <Link
              to="/profile"
              onClick={handleClose}
              className="flex items-center gap-2"
            >
              <User className="h-4 w-4" />
              {translate("crm.profile.title")}
            </Link>
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => logout()} className="cursor-pointer">
            <LogOut className="mr-2 h-4 w-4" />
            {translate("ra.auth.logout")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </UserMenuContext.Provider>
  );
}
