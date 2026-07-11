import { Bell } from "lucide-react";
import { Link } from "react-router";

import { UserMenu } from "@/components/admin/user-menu";

import { useConfigurationContext } from "../root/ConfigurationContext";
import { useNotifications } from "./topbar/useNotifications";

const Header = () => {
  const { title } = useConfigurationContext();
  const { count } = useNotifications();

  return (
    <header className="workspace-topbar">
      <Link to="/" className="workspace-topbar-brand" aria-label={title}>
        <img src="/ttsoft-logo.png" alt="" aria-hidden="true" />
        <span>Ting Ting Soft</span>
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
