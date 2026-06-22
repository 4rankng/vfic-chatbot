import { Bell } from "lucide-react";
import { useNavigate } from "react-router";

import { Button } from "@/components/ui/button";

import { useNotifications } from "./useNotifications";

/**
 * Notifications bell shared by the desktop and mobile topbars. Shows a pulsing
 * brand-colored dot when conversations need human takeover, and navigates to the
 * filtered takeover queue on click (instead of only showing a toast).
 */
export const NotificationsBell = () => {
  const navigate = useNavigate();
  const { hasNotifications } = useNotifications();

  const handleClick = () => {
    navigate(
      `/conversations?filter=${encodeURIComponent(JSON.stringify({ mode: "human" }))}`,
    );
  };

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={handleClick}
      aria-label="Thông báo"
      className="relative h-9 w-9 rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
    >
      <Bell className="h-5 w-5" />
      {hasNotifications && (
        <span className="absolute right-1.5 top-1.5 flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
        </span>
      )}
    </Button>
  );
};
