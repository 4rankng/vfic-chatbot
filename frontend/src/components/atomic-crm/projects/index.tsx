import { lazy } from "react";
import type { Project } from "../types";

const ProjectList = lazy(() =>
  import("./ProjectList").then((m) => ({ default: m.ProjectList })),
);
const ProjectCreate = lazy(() =>
  import("./ProjectCreate").then((m) => ({ default: m.ProjectCreate })),
);
const ProjectEdit = lazy(() =>
  import("./ProjectEdit").then((m) => ({ default: m.ProjectEdit })),
);
const ProjectShow = lazy(() =>
  import("./ProjectShow").then((m) => ({ default: m.ProjectShow })),
);

// "Project" = a product in the agent's master index (e.g. the LG Display factory).
// Admins create/activate projects and upload KB under them.
export default {
  list: ProjectList,
  show: ProjectShow,
  create: ProjectCreate,
  edit: ProjectEdit,
  recordRepresentation: (record?: Project) => record?.name ?? "Project",
};
