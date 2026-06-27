import type { Project } from "../types";
import { ProjectList } from "./ProjectList";
import { ProjectCreate } from "./ProjectCreate";
import { ProjectEdit } from "./ProjectEdit";
import { ProjectShow } from "./ProjectShow";

// "Project" = a product in the agent's master index (e.g. the LG Display factory).
// Admins create/activate projects, upload KB under them, and refresh the catalog card.
export default {
  list: ProjectList,
  show: ProjectShow,
  create: ProjectCreate,
  edit: ProjectEdit,
  recordRepresentation: (record?: Project) => record?.name ?? "Project",
};
