import { Link, useLocation } from "react-router";
import {
  Briefcase,
  Gauge,
  Home,
  MessageCircle,
  Settings,
  UserRound,
  type LucideIcon,
} from "lucide-react";

import { useRoleActions } from "../hooks/useRoleActions";

type WorkspaceNavKey =
  | "home"
  | "conversations"
  | "projects"
  | "settings"
  | "performance"
  | "account";

type WorkspaceNavItem = {
  key: WorkspaceNavKey;
  label: string;
  Icon: LucideIcon;
  href: string;
  // adminOnly items are hidden from non-admin roles (e.g. recruiter) so they
  // never reach an admin-gated endpoint and hit a 403 error state.
  adminOnly?: boolean;
};

const WORKSPACE_NAV_ITEMS: WorkspaceNavItem[] = [
  {
    key: "conversations",
    label: "Chat",
    Icon: MessageCircle,
    href: "/conversations",
  },
  {
    key: "projects",
    label: "Dự án",
    Icon: Briefcase,
    href: "/projects",
  },
  {
    key: "settings",
    label: "Settings",
    Icon: Settings,
    href: "/settings",
  },
  {
    key: "performance",
    label: "Hiệu suất",
    Icon: Gauge,
    href: "/hieu-suat",
    adminOnly: true,
  },
  { key: "account", label: "Account", Icon: UserRound, href: "/profile" },
];

const getActiveWorkspaceKey = (pathname: string): WorkspaceNavKey => {
  if (pathname.startsWith("/hieu-suat")) return "performance";
  if (pathname.startsWith("/profile")) return "account";
  if (pathname.startsWith("/users")) return "account";
  if (pathname.startsWith("/projects")) return "projects";
  if (pathname.startsWith("/knowledge_sources")) return "settings";
  if (pathname.startsWith("/personas")) return "settings";
  if (pathname.startsWith("/settings")) return "settings";
  if (pathname.startsWith("/zalo_integrations")) return "settings";
  if (pathname.startsWith("/conversations")) return "conversations";
  return "home";
};

export const WorkspaceIconRail = () => {
  const location = useLocation();
  const { isAdmin } = useRoleActions();
  const activeKey = getActiveWorkspaceKey(location.pathname);
  const navItems = isAdmin
    ? WORKSPACE_NAV_ITEMS
    : WORKSPACE_NAV_ITEMS.filter((item) => !item.adminOnly);

  return (
    <nav className="workspace-icon-rail" aria-label="Điều hướng workspace">
      <Link
        to="/"
        className={`workspace-logo-tile ${activeKey === "home" ? "active" : ""}`}
        aria-label="Dashboard"
        title="Dashboard"
      >
        <Home className="icon" aria-hidden="true" />
      </Link>
      <div className="workspace-icon-stack">
        {navItems.map(({ key, label, Icon, href }) => (
          <Link
            key={key}
            to={href}
            className={`workspace-icon-action ${activeKey === key ? "active" : ""}`}
            aria-label={label}
            title={label}
          >
            <Icon className="icon" aria-hidden="true" />
          </Link>
        ))}
      </div>
    </nav>
  );
};
