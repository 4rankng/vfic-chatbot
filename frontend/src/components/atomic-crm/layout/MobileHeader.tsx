import { Bell } from "lucide-react";
import { UserMenu } from "@/components/admin/user-menu";
import { Button } from "@/components/ui/button";
import { useNotify, useGetList } from "ra-core";
import type { Conversation } from "../types";

const MobileHeader = ({ children }: { children: React.ReactNode }) => {
  const notify = useNotify();

  // Fetch conversations to dynamically check if any require attention (human response needed)
  const { data: allConversations } = useGetList<Conversation>("conversations", {
    pagination: { page: 1, perPage: 100 },
  });

  const unreadConvs = allConversations?.filter((c) => c.mode === "human").length || 0;
  const hasNotifications = unreadConvs > 0;

  const handleBellClick = () => {
    if (unreadConvs > 0) {
      notify(`You have ${unreadConvs} conversation(s) needing attention`, { type: "info" });
    } else {
      notify("You have no new notifications", { type: "info" });
    }
  };

  return (
    <header className="fixed top-0 left-0 right-0 z-10 bg-background border-b border-border h-14 px-4 w-full flex justify-between items-center">
      <div className="flex items-center min-w-0">
        {children}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <Button
          variant="ghost"
          size="icon"
          className="relative text-foreground h-8 w-8 rounded-full"
          onClick={handleBellClick}
        >
          <Bell className="h-5 w-5" />
          {hasNotifications && (
            <span className="absolute top-1 right-1 flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
            </span>
          )}
        </Button>
        <UserMenu />
      </div>
    </header>
  );
};

export default MobileHeader;
