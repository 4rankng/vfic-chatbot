import { Card, CardContent } from "@/components/ui/card";
import { EditBase, Form, useEditContext, useNotify, useRefresh, type MutationMode } from "ra-core";

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
  const { isPending, record, save } = useEditContext<Contact>();
  const notify = useNotify();
  const refresh = useRefresh();

  if (isPending || !record) return null;

  const handleSave = async (values: Record<string, unknown>) => {
    try {
      const data = { ...values, version: (record as Record<string, unknown>).version } as Record<string, unknown>;
      return await save?.(data);
    } catch (error: any) {
      const status = error?.status || error?.body?.status;
      const detail = error?.body?.detail || error?.message;
      if (status === 409) {
        notify(detail || "Vừa được nhân viên khác thay đổi. Vui lòng làm mới.", {
          type: "warning",
          undoable: true,
          action: () => {
            refresh();
          },
          actionLabel: "Làm mới",
        });
        refresh();
      }
      throw error; // Let react-admin also handle it
    }
  };

  return (
    <div className="mt-2 flex gap-8">
      <Form className="flex flex-1 flex-col gap-4" record={record} onSubmit={handleSave}>
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
