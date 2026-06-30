import { lazy } from "react";
import type { Lead } from "../types";

const LeadList = lazy(() =>
  import("./LeadList").then((m) => ({ default: m.LeadList })),
);
const LeadShow = lazy(() =>
  import("./LeadShow").then((m) => ({ default: m.LeadShow })),
);
const ContactCreate = lazy(() =>
  import("./LeadCreate").then((m) => ({ default: m.ContactCreate })),
);
const ContactEdit = lazy(() =>
  import("./LeadEdit").then((m) => ({ default: m.ContactEdit })),
);

export default {
  list: LeadList,
  show: LeadShow,
  create: ContactCreate,
  edit: ContactEdit,
  recordRepresentation: (record?: Lead) => record?.name || "Unnamed Lead",
};
