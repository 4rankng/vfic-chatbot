import { Bell } from "lucide-react";
import { Link } from "react-router";

import { UserMenu } from "@/components/admin/user-menu";

import { useInstallationContext } from "../installation/installation-context";
import { useNotifications } from "./topbar/useNotifications";
import { getWorkspaceDestination } from "./workspace-navigation";

const Header = () => {
  const { manifest } = useInstallationContext();
  const title =
    manifest.lifecycle === "ACTIVE"
      ? manifest.branding?.app_name?.trim() ||
        manifest.customer_identity?.display_name.trim() ||
        "Ting Ting"
      : "Ting Ting";
  const { count } = useNotifications();
  const messagesDestination = getWorkspaceDestination(
    { id: "messages", to: "/conversations" },
    count,
  );

  return (
    <header className="workspace-topbar tt-navbar">
      <Link to="/" className="workspace-topbar-brand" aria-label={title}>
        <img src="/ttsoft-logo.png" alt="" aria-hidden="true" />
        <span>{title}</span>
      </Link>

      <div className="workspace-topbar-actions tt-navbar-end">
        <Link
          to={messagesDestination}
          className="workspace-topbar-notifications tt-btn tt-btn-ghost tt-btn-circle"
          aria-label={
            count > 0
              ? `${count} cuộc trò chuyện cần chú ý`
              : "Không có thông báo mới"
          }
        >
          <Bell aria-hidden="true" />
          {count > 0 ? (
            <span className="workspace-topbar-badge tt-badge tt-badge-error tt-badge-xs">
              {count > 99 ? "99+" : count}
            </span>
          ) : null}
        </Link>
        <UserMenu variant="topbar" />
      </div>
    </header>
  );
};

export default Header;
