import { lazy } from "react";
import { Files } from "lucide-react";

const CaseList = lazy(() =>
  import("./CaseList").then((module) => ({ default: module.CaseList })),
);
const CaseCreate = lazy(() =>
  import("./CaseForm").then((module) => ({ default: module.CaseCreate })),
);
const CaseEdit = lazy(() =>
  import("./CaseForm").then((module) => ({ default: module.CaseEdit })),
);

export default {
  list: CaseList,
  create: CaseCreate,
  edit: CaseEdit,
  icon: Files,
  recordRepresentation: (record: { case_no?: number; subject?: string | null }) =>
    record.subject || (record.case_no ? `Hồ sơ #${record.case_no}` : "Hồ sơ"),
};
