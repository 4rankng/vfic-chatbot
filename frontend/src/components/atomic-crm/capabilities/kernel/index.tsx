import { Navigate } from "react-router";
import {
  Briefcase,
  Gauge,
  Home,
  MessageCircle,
  Settings,
  UserRound,
} from "lucide-react";

import users from "../../users";
import conversations from "../../conversations";
import automation from "../../automation";
import knowledge from "../../knowledge";
import knowledgeBases from "../../knowledge-base";
import projects from "../../projects";
import personas from "../../personas";
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
      pathStartsWith("/knowledge_bases")(path) ||
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
  "kernel.resource.knowledge-sources": {
    kind: "resource" as const,
    resource: {
      id: "kernel.resource.knowledge-sources",
      name: "knowledge_sources",
      props: knowledge,
    },
  },
  "kernel.resource.knowledge-bases": {
    kind: "resource" as const,
    resource: {
      id: "kernel.resource.knowledge-bases",
      name: "knowledge_bases",
      props: knowledgeBases,
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
  "kernel.resource.personas": {
    kind: "resource" as const,
    resource: {
      id: "kernel.resource.personas",
      name: "personas",
      props: personas,
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
