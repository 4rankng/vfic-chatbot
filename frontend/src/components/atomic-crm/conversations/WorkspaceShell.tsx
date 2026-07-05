import { Link, useLocation } from "react-router";
import {
  BotMessageSquare,
  BookOpen,
  Briefcase,
  Home,
  MessageCircle,
  Settings,
  UserRound,
  type LucideIcon,
} from "lucide-react";

type WorkspaceNavKey =
  | "home"
  | "conversations"
  | "personas"
  | "knowledge"
  | "projects"
  | "settings";

type WorkspaceNavItem = {
  key: WorkspaceNavKey;
  label: string;
  Icon: LucideIcon;
  href: string;
};

const WORKSPACE_NAV_ITEMS: WorkspaceNavItem[] = [
  { key: "home", label: "Trang chính", Icon: Home, href: "/" },
  {
    key: "conversations",
    label: "Tin nhắn",
    Icon: MessageCircle,
    href: "/conversations",
  },
  {
    key: "personas",
    label: "Agent",
    Icon: BotMessageSquare,
    href: "/personas",
  },
  {
    key: "knowledge",
    label: "Training",
    Icon: BookOpen,
    href: "/knowledge_sources",
  },
  { key: "projects", label: "Dự án", Icon: Briefcase, href: "/projects" },
  {
    key: "settings",
    label: "Cài đặt",
    Icon: Settings,
    href: "/settings",
  },
];

const getActiveWorkspaceKey = (pathname: string): WorkspaceNavKey => {
  if (pathname.startsWith("/knowledge_sources")) return "knowledge";
  if (pathname.startsWith("/personas")) return "personas";
  if (pathname.startsWith("/projects")) return "projects";
  if (pathname.startsWith("/settings")) return "settings";
  if (pathname.startsWith("/zalo_integrations")) return "settings";
  if (pathname.startsWith("/conversations")) return "conversations";
  return "home";
};

export const WorkspaceIconRail = () => {
  const location = useLocation();
  const activeKey = getActiveWorkspaceKey(location.pathname);

  return (
    <nav className="workspace-icon-rail" aria-label="Điều hướng workspace">
      <Link
        to="/"
        className="workspace-logo-tile"
        aria-label="Mở workspace Ting Ting Soft"
        title="Ting Ting Soft"
      >
        <img
          src="/ttsoft-logo.png"
          alt=""
          className="workspace-logo-mark"
          aria-hidden="true"
        />
      </Link>
      <div className="workspace-icon-stack">
        {WORKSPACE_NAV_ITEMS.map(({ key, label, Icon, href }) => (
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
      <div className="workspace-rail-user" aria-label="Người dùng hiện tại">
        <UserRound className="icon" aria-hidden="true" />
      </div>
    </nav>
  );
};
