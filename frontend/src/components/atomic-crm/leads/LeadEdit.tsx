import { Card, CardContent } from "@/components/ui/card";
import { EditBase, Form, useEditContext, type MutationMode } from "ra-core";

import type { Contact } from "../types";
import { ContactAside } from "./ContactAside";
import { ContactInputs } from "./ContactInputs";
import { FormToolbar } from "../layout/FormToolbar";

export const ContactEdit = ({
  mutationMode,
}: {
  mutationMode?: MutationMode;
}) => (
  <EditBase redirect="show" mutationMode={mutationMode}>
    <ContactEditContent />
  </EditBase>
);

const ContactEditContent = () => {
  const { isPending, record } = useEditContext<Contact>();
  if (isPending || !record) return null;
  return (
    <div className="mt-2 flex gap-8">
      <Form className="flex flex-1 flex-col gap-4" record={record}>
        <Card>
          <CardContent>
            <ContactInputs />
            <FormToolbar />
          </CardContent>
        </Card>
      </Form>

      <ContactAside />
    </div>
  );
};
