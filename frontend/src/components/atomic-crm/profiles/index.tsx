import { ProfileList } from "./ProfileList";
import { ProfileCreate } from "./ProfileCreate";
import type { Profile } from "../types";

export default {
  list: ProfileList,
  create: ProfileCreate,
  recordRepresentation: (record: Profile) => record?.full_name,
};
