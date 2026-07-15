import { lazy } from "react";
import { ContactRound } from "lucide-react";

const ContactList = lazy(() =>
  import("./ContactList").then((module) => ({ default: module.ContactList })),
);
const ContactCreate = lazy(() =>
  import("./ContactForm").then((module) => ({ default: module.ContactCreate })),
);
const ContactEdit = lazy(() =>
  import("./ContactForm").then((module) => ({ default: module.ContactEdit })),
);

export default {
  list: ContactList,
  create: ContactCreate,
  edit: ContactEdit,
  icon: ContactRound,
  recordRepresentation: (record: {
    id?: string;
    display_name?: string | null;
    primary_phone?: string | null;
    primary_email?: string | null;
    primary_channel?: { provider?: string | null; external_id?: string | null } | null;
  }) =>
    record.display_name ||
    record.primary_phone ||
    record.primary_email ||
    record.primary_channel?.external_id ||
    record.primary_channel?.provider ||
    "Chưa có tên",
};
