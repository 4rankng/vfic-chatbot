import { Navigate } from "react-router";
import {
  Briefcase,
  Gauge,
  Home,
  MessageCircle,
  ScrollText,
  Settings,
  Users,
} from "lucide-react";

import users from "../../users";
import conversations from "../../conversations";
import automation from "../../automation";
import projects from "../../projects";
import integrations from "../../integrations";
import type {
  CompiledDestination,
  CompiledRoute,
  ExecutableCapabilityModule,
} from "../types";
import {
  AdminPerformanceRoute,
  ForgotPasswordPage,
  ProfilePage,
  RouteBoundary,
} from "./components";

const pathStartsWith = (prefix: string) => (path: string) =>
  path === prefix || path.startsWith(`${prefix}/`);

const navigation: readonly CompiledDestination[] = [
  {
    id: "overview",
    label: "Tổng quan",
    to: "/",
    Icon: Home,
    section: "operations",
    isActive: (path) => path === "/",
  },
  {
    id: "messages",
    label: "Tin nhắn",
    to: "/conversations",
    Icon: MessageCircle,
    section: "operations",
    isActive: pathStartsWith("/conversations"),
  },
  {
    id: "projects",
    label: "Dự án",
    to: "/projects",
    Icon: Briefcase,
    section: "operations",
    isActive: pathStartsWith("/projects"),
  },
  {
    id: "users",
    label: "Người dùng",
    to: "/users",
    Icon: Users,
    roles: ["admin"],
    section: "team",
    isActive: pathStartsWith("/users"),
  },
  {
    id: "settings",
    label: "Cài đặt",
    to: "/settings",
    Icon: Settings,
    roles: ["admin"],
    section: "system",
    isActive: (path) =>
      pathStartsWith("/settings")(path) ||
      pathStartsWith("/zalo_integrations")(path),
  },
  {
    id: "bot_runs",
    label: "Nhật ký bot",
    to: "/bot_runs",
    Icon: ScrollText,
    roles: ["admin"],
    section: "system",
    isActive: pathStartsWith("/bot_runs"),
  },
  {
    id: "performance",
    label: "Hiệu suất",
    to: "/hieu-suat",
    Icon: Gauge,
    roles: ["admin"],
    section: "system",
    isActive: pathStartsWith("/hieu-suat"),
  },
];

const routes: readonly CompiledRoute[] = [
  {
    id: "kernel.route.performance",
    path: "/hieu-suat",
    layout: "layout",
    Component: () => (
      <RouteBoundary>
        <AdminPerformanceRoute />
      </RouteBoundary>
    ),
  },
  {
    id: "kernel.route.profile",
    path: "/profile",
    layout: "layout",
    Component: () => (
      <RouteBoundary>
        <ProfilePage />
      </RouteBoundary>
    ),
  },
  {
    id: "kernel.route.settings-profile-redirect",
    path: "/settings/profile",
    layout: "layout",
    Component: () => <Navigate to="/profile" replace />,
  },
  {
    id: "channel.zalo.route.legacy-settings-redirect",
    path: "/zalo_integrations/*",
    layout: "layout",
    Component: () => <Navigate to="/settings" replace />,
  },
  {
    id: "kernel.route.forgot-password",
    path: "/forgot-password",
    layout: "no-layout",
    Component: () => (
      <RouteBoundary>
        <ForgotPasswordPage />
      </RouteBoundary>
    ),
  },
];

const resourceContributions = {
  "kernel.resource.conversations": {
    kind: "resource" as const,
    resource: {
      id: "kernel.resource.conversations",
      name: "conversations",
      props: conversations,
    },
  },
  "kernel.resource.bot-runs": {
    kind: "resource" as const,
    resource: {
      id: "kernel.resource.bot-runs",
      name: "bot_runs",
      props: automation,
    },
  },
  "kernel.resource.projects": {
    kind: "resource" as const,
    resource: {
      id: "kernel.resource.projects",
      name: "projects",
      props: projects,
    },
  },
  "kernel.resource.settings": {
    kind: "resource" as const,
    resource: {
      id: "kernel.resource.settings",
      name: "settings",
      props: integrations,
    },
  },
  "kernel.resource.users": {
    kind: "resource" as const,
    resource: { id: "kernel.resource.users", name: "users", props: users },
  },
};

export const contributions: ExecutableCapabilityModule["contributions"] = {
  ...resourceContributions,
  ...Object.fromEntries(
    routes.map((route) => [route.id, { kind: "route" as const, route }]),
  ),
  ...Object.fromEntries(
    navigation.map((destination) => [
      `kernel.navigation.${destination.id}`,
      { kind: "navigation" as const, destination },
    ]),
  ),
};
