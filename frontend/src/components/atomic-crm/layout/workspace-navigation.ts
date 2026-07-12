import {
  Briefcase,
  Gauge,
  Home,
  MessageCircle,
  Settings,
  UserRound,
  type LucideIcon,
} from "lucide-react";

export type WorkspaceRole = "admin" | "recruiter";
export type WorkspaceNavigationSurface = "rail" | "mobile";

export type WorkspaceDestination = {
  id:
    | "overview"
    | "messages"
    | "projects"
    | "settings"
    | "performance"
    | "account";
  label: string;
  to: string;
  Icon: LucideIcon;
  roles?: readonly WorkspaceRole[];
  rail: boolean;
  mobile: boolean;
  isActive: (normalizedPath: string) => boolean;
};

const pathStartsWith = (prefix: string) => (path: string) =>
  path === prefix || path.startsWith(`${prefix}/`);

export const normalizeWorkspacePath = (value: string): string => {
  const hashPath = value.startsWith("#") ? value.slice(1) : value;
  const path = hashPath.split(/[?#]/, 1)[0] || "/";
  return path.startsWith("/") ? path : `/${path}`;
};

export const WORKSPACE_DESTINATIONS: readonly WorkspaceDestination[] = [
  {
    id: "overview",
    label: "Tổng quan",
    to: "/",
    Icon: Home,
    rail: true,
    mobile: true,
    isActive: (path) => path === "/",
  },
  {
    id: "messages",
    label: "Tin nhắn",
    to: "/conversations",
    Icon: MessageCircle,
    rail: true,
    mobile: true,
    isActive: pathStartsWith("/conversations"),
  },
  {
    id: "projects",
    label: "Dự án",
    to: "/projects",
    Icon: Briefcase,
    rail: true,
    mobile: true,
    isActive: pathStartsWith("/projects"),
  },
  {
    id: "settings",
    label: "Cài đặt",
    to: "/settings",
    Icon: Settings,
    roles: ["admin"],
    rail: true,
    mobile: true,
    isActive: (path) =>
      pathStartsWith("/settings")(path) ||
      pathStartsWith("/zalo_integrations")(path) ||
      pathStartsWith("/knowledge_sources")(path) ||
      pathStartsWith("/personas")(path),
  },
  {
    id: "performance",
    label: "Hiệu suất",
    to: "/hieu-suat",
    Icon: Gauge,
    roles: ["admin"],
    rail: true,
    mobile: false,
    isActive: pathStartsWith("/hieu-suat"),
  },
  {
    id: "account",
    label: "Tài khoản",
    to: "/profile",
    Icon: UserRound,
    rail: false,
    mobile: true,
    isActive: (path) =>
      pathStartsWith("/profile")(path) || pathStartsWith("/users")(path),
  },
];

export const getWorkspaceDestinations = (
  role: WorkspaceRole,
  surface: WorkspaceNavigationSurface,
): readonly WorkspaceDestination[] =>
  WORKSPACE_DESTINATIONS.filter(
    (destination) =>
      destination[surface] &&
      (!destination.roles || destination.roles.includes(role)) &&
      // Mobile has four fixed role-aware destinations. Account remains the
      // recruiter escape hatch, while administrators use Cài đặt instead.
      (surface !== "mobile" ||
        (role === "admin"
          ? destination.id !== "account"
          : destination.id !== "settings" && destination.id !== "performance")),
  );

/**
 * Mobile keeps four primary destinations visible. This helper exposes every
 * remaining destination through the overflow surface, including Account for
 * administrators. Account owns profile and logout, so it must stay reachable
 * even though it does not occupy a fixed admin navigation slot.
 */
export const getWorkspaceOverflowDestinations = (
  role: WorkspaceRole,
): readonly WorkspaceDestination[] => {
  const primaryIds = new Set(
    getWorkspaceDestinations(role, "mobile").map(({ id }) => id),
  );

  return WORKSPACE_DESTINATIONS.filter(
    (destination) =>
      (destination.rail || destination.mobile) &&
      (!destination.roles || destination.roles.includes(role)) &&
      !primaryIds.has(destination.id),
  );
};
