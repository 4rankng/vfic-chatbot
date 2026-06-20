import type { Lead } from "../types";
import { LeadList } from "./LeadList";
import { LeadShow } from "./LeadShow";
import { ContactCreate } from "./LeadCreate";
import { ContactEdit } from "./LeadEdit";

export default {
  list: LeadList,
  show: LeadShow,
  create: ContactCreate,
  edit: ContactEdit,
  recordRepresentation: (record?: Lead) => record?.name || "Unnamed Lead",
};
