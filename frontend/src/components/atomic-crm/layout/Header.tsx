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
      className="workspace-sidebar-brand-full"
      src="/brand/tinghire-logo.png"
      alt=""
      aria-hidden="true"
      width="1440"
      height="320"
    />
    <img
      className="workspace-sidebar-brand-mark"
      src="/brand/tinghire-icon-192.png"
      alt=""
      aria-hidden="true"
      width="192"
      height="192"
    />
  </Link>
);

const Header = () => {
  const { count } = useNotifications();

  return (
    <header className="workspace-topbar tt-navbar">
      <Link to="/" className="workspace-topbar-brand" aria-label="TingHire">
        <img src="/brand/tinghire-icon-192.png" alt="" aria-hidden="true" />
        <span>TingHire</span>
      </Link>

      <div className="workspace-topbar-actions tt-navbar-end">
        <NotificationsPopover count={count} />
        <UserMenu variant="topbar" />
      </div>
    </header>
  );
};

export default Header;
