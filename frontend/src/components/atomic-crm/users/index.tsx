import { lazy } from "react";
import { UserCog } from "lucide-react";
import type { UserAccount } from "../types";

const UserList = lazy(() =>
  import("./UserList").then((m) => ({ default: m.UserList })),
);
const UserCreate = lazy(() =>
  import("./UserCreate").then((m) => ({ default: m.UserCreate })),
);
const UserEdit = lazy(() =>
  import("./UserEdit").then((m) => ({ default: m.UserEdit })),
);

export default {
  list: UserList,
  create: UserCreate,
  edit: UserEdit,
  icon: UserCog,
  recordRepresentation: (record: UserAccount) =>
    record?.full_name || record?.email,
};
