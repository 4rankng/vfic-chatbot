// Compatibility shim — original SalesInputs was removed during the Contact→Lead
// refactor. Stub a minimal form so the profile-edit screen keeps compiling.
import { TextInput } from "@/components/admin/text-input";
import { BooleanInput } from "@/components/admin/boolean-input";

export const SalesInputs = () => (
  <div className="flex flex-col gap-4">
    <TextInput source="first_name" />
    <TextInput source="last_name" />
    <TextInput source="email" type="email" />
    <TextInput source="password" type="password" />
    <BooleanInput source="administrator" />
  </div>
);
