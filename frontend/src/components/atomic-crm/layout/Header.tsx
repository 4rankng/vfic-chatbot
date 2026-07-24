import { Link } from "react-router";

import { UserMenu } from "@/components/admin/user-menu";

import { useNotifications } from "./topbar/useNotifications";
import { NotificationsPopover } from "./topbar/NotificationsPopover";

export const WorkspaceSidebarBrand = () => (
  <Link
    to="/"
    className="workspace-sidebar-brand"
    aria-label="TingHire - về trang tổng quan"
  >
    <img
      className="workspace-sidebar-brand-mark"
      src="/brand/tinghire-icon-rail.png"
      alt=""
      aria-hidden="true"
      width="131"
      height="106"
    />
  </Link>
);

const Header = () => {
  const { count } = useNotifications();

  return (
    <header className="workspace-topbar">
      <Link to="/" className="workspace-topbar-brand" aria-label="TingHire">
        <img
          src="/brand/tinghire-icon-transparent.png"
          alt=""
          aria-hidden="true"
        />
        <span>TingHire</span>
      </Link>

      <div className="workspace-topbar-actions">
        <NotificationsPopover count={count} />
        <UserMenu variant="topbar" />
      </div>
    </header>
  );
};

export default Header;
