import { useCallback, useState } from "react";
import {
  Translate,
  useAuthProvider,
  useGetIdentity,
  useLogout,
  UserMenuContext,
} from "ra-core";
import { LogOut, User } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";

export type UserMenuProps = {};

/**
 * A user menu component displayed in the top right corner of the admin layout.
 *
 * Provides access to user-related actions such as profile, settings, and logout.
 * Displays the user's avatar and name from the identity provider, and includes a logout option.
 * Only displays in applications using authentication.
 *
 * @see {@link https://marmelab.com/shadcn-admin-kit/docs/usermenu UserMenu documentation}
 */
export function UserMenu() {
  const authProvider = useAuthProvider();
  const { data: identity } = useGetIdentity();
  const logout = useLogout();

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
            className="relative h-8 w-8 ml-2 rounded-full"
          >
            <Avatar className="h-8 w-8">
              <AvatarImage src={identity?.avatar} role="presentation" />
              <AvatarFallback>
                <User className="size-4" />
              </AvatarFallback>
            </Avatar>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-32" align="end" forceMount>
          <DropdownMenuItem onClick={() => logout()} className="cursor-pointer">
            <LogOut className="mr-2 h-4 w-4" />
            <Translate i18nKey="ra.auth.logout">Log out</Translate>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </UserMenuContext.Provider>
  );
}
