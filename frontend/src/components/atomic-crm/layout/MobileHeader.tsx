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
      notify(`Bạn có ${unreadConvs} cuộc trò chuyện cần phản hồi`, { type: "info" });
    } else {
      notify("Bạn không có thông báo mới", { type: "info" });
    }
  };

  return (
    <header className="fixed top-0 left-0 right-0 z-10 bg-white dark:bg-card border-b border-border shadow-[0_1px_3px_rgba(0,0,0,0.05)] h-16 px-4 w-full flex justify-between items-center">
      <div className="flex items-center min-w-0">
        {children}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <Button
          variant="ghost"
          size="icon"
          className="h-9 w-9 rounded-full text-muted-foreground hover:text-foreground hover:bg-muted transition-colors relative"
          onClick={handleBellClick}
        >
          <Bell className="h-5 w-5" />
          {hasNotifications && (
            <span className="absolute top-1.5 right-1.5 flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full bg-blue-600 rounded-full opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-600"></span>
            </span>
          )}
        </Button>
        <UserMenu />
      </div>
    </header>
  );
};

export default MobileHeader;
