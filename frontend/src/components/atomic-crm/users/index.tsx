import { UserCog } from "lucide-react";
import type { UserAccount } from "../types";
import { UserCreate } from "./UserCreate";
import { UserEdit } from "./UserEdit";
import { UserList } from "./UserList";

export default {
  list: UserList,
  create: UserCreate,
  edit: UserEdit,
  icon: UserCog,
  recordRepresentation: (record: UserAccount) => record?.full_name || record?.email,
};
