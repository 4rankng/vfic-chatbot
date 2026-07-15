import { Bell } from "lucide-react";
import { Link } from "react-router";

import { UserMenu } from "@/components/admin/user-menu";

import { useInstallationContext } from "../installation/installation-context";
import { useNotifications } from "./topbar/useNotifications";

const Header = () => {
  const { manifest } = useInstallationContext();
  const title =
    manifest.lifecycle === "ACTIVE"
      ? manifest.branding?.app_name?.trim() ||
        manifest.customer_identity?.display_name.trim()
      : "";
  const { count } = useNotifications();

  return (
    <header className="workspace-topbar">
      <Link to="/" className="workspace-topbar-brand" aria-label={title}>
        <span>{title}</span>
      </Link>

      <div className="workspace-topbar-actions">
        <Link
          to="/conversations"
          className="workspace-topbar-notifications"
          aria-label={
            count > 0
              ? `${count} cuộc trò chuyện cần chú ý`
              : "Không có thông báo mới"
          }
        >
          <Bell aria-hidden="true" />
          {count > 0 ? (
            <span className="workspace-topbar-badge">
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
