import { Link } from "react-router";

import { UserMenu } from "@/components/admin/user-menu";

import { useInstallationContext } from "../installation/installation-context";
import { useNotifications } from "./topbar/useNotifications";
import { NotificationsPopover } from "./topbar/NotificationsPopover";

const Header = () => {
  const { manifest } = useInstallationContext();
  const title =
    manifest.lifecycle === "ACTIVE"
      ? manifest.branding?.app_name?.trim() ||
        manifest.customer_identity?.display_name.trim() ||
        "Ting Ting"
      : "Ting Ting";
  const { count } = useNotifications();

  return (
    <header className="workspace-topbar tt-navbar">
      <Link to="/" className="workspace-topbar-brand" aria-label={title}>
        <img src="/ttsoft-logo.png" alt="" aria-hidden="true" />
        <span>{title}</span>
      </Link>

      <div className="workspace-topbar-actions tt-navbar-end">
        <NotificationsPopover count={count} />
        <UserMenu variant="topbar" />
      </div>
    </header>
  );
};

export default Header;
