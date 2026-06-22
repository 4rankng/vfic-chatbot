import { CreateBase, Form, type MutationMode } from "ra-core";
import { Card, CardContent } from "@/components/ui/card";

import { ContactInputs } from "./ContactInputs";
import { FormToolbar } from "../layout/FormToolbar";

// The VFIC `leads` table has no sales_id / email_jsonb / phone_jsonb /
// first_seen / last_seen / tags columns (those belong to the legacy Contact
// schema), so the create form must submit only real Lead fields. zalo_id is
// nullable and status/created_at/updated_at have DB defaults, so a manually
// created lead inserts cleanly.
export const ContactCreate = ({
  mutationMode,
}: {
  mutationMode?: MutationMode;
}) => (
  <CreateBase redirect="show" mutationMode={mutationMode}>
    <div className="mt-2 flex lg:mr-72">
      <div className="flex-1">
        <Form defaultValues={{ lead_stage: "NEW" }}>
          <Card>
            <CardContent>
              <ContactInputs />
              <FormToolbar />
            </CardContent>
          </Card>
        </Form>
      </div>
    </div>
  </CreateBase>
);
