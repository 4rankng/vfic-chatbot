// Minimal compatibility stub. The legacy ContactInputs form lived in this
// folder's broken `LeadInputs.tsx`. The current VFIC app's create/edit form
// for leads is handled through the LeadChat conversation flow, so a stub
// suffices to keep the surrounding files type-checking until a real form is
// reintroduced.
import { Card, CardContent } from "@/components/ui/card";
import { TextInput } from "@/components/admin/text-input";
import { SelectInput } from "@/components/admin/select-input";
import { LEAD_SCORES, LEAD_STAGES } from "../types";

export const ContactInputs = () => (
  <Card>
    <CardContent className="flex flex-col gap-4 pt-4">
      <TextInput source="name" />
      <TextInput source="phone" />
      <TextInput source="desired_job" />
      <TextInput source="expected_salary" />
      <SelectInput
        source="lead_stage"
        choices={LEAD_STAGES as unknown as { value: string; label: string }[]}
        optionText="label"
        optionValue="value"
      />
      <SelectInput
        source="lead_score"
        choices={LEAD_SCORES as unknown as { value: string; label: string }[]}
        optionText="label"
        optionValue="value"
      />
    </CardContent>
  </Card>
);
