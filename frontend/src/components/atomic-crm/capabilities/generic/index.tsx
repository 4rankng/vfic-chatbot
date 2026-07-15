import { Navigate } from "react-router";

import contacts from "../../contacts";
import cases from "../../cases";
import conversations from "../../conversations";
import users from "../../users";
import { WorkflowAuthoringPage } from "../../workflows/WorkflowAuthoringPage";
import type { ExecutableCapabilityModule } from "../types";

const GenericDashboard = () => (
  <main className="p-6">
    <h1 className="text-page-title font-bold">Tổng quan</h1>
  </main>
);

export const contributions: ExecutableCapabilityModule["contributions"] = {
  "kernel.resource.contacts": {
    kind: "resource",
    resource: { id: "kernel.resource.contacts", name: "contacts", props: contacts },
  },
  "kernel.resource.cases": {
    kind: "resource",
    resource: { id: "kernel.resource.cases", name: "cases", props: cases },
  },
  "kernel.resource.generic-conversations": {
    kind: "resource",
    resource: {
      id: "kernel.resource.generic-conversations",
      name: "conversations",
      props: conversations,
    },
  },
  "kernel.resource.generic-users": {
    kind: "resource",
    resource: { id: "kernel.resource.generic-users", name: "users", props: users },
  },
  "kernel.dashboard.generic": {
    kind: "dashboard",
    dashboard: GenericDashboard,
  },
  "kernel.route.workflow-authoring": {
    kind: "route",
    route: {
      id: "kernel.route.workflow-authoring",
      path: "/settings/workflows/new",
      layout: "layout",
      Component: WorkflowAuthoringPage,
    },
  },
  "kernel.route.generic-profile": {
    kind: "route",
    route: {
      id: "kernel.route.generic-profile",
      path: "/profile",
      layout: "layout",
      Component: () => <Navigate to="/contacts" replace />,
    },
  },
};
