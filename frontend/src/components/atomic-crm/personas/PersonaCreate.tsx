import { CreateBase, useDataProvider, useNotify, useRedirect } from "ra-core";
import { TopToolbar } from "../layout/TopToolbar";
import { PersonaForm, type PersonaValues } from "./PersonaForm";
import type { CrmDataProvider } from "../providers/rest/dataProvider";

export const PersonaCreate = () => {
  const notify = useNotify();
  const redirect = useRedirect();
  const dataProvider = useDataProvider<CrmDataProvider>();

  const onSubmit = async (v: PersonaValues) => {
    try {
      await dataProvider.create("personas", {
        data: { name: v.name, body_md: v.body_md, notes: v.notes || null },
      });
      notify("Đã tạo Agent.", { type: "success" });
      redirect("/personas");
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    }
  };

  return (
    <CreateBase resource="personas">
      <div className="mx-auto w-full max-w-6xl">
        <TopToolbar>
          <h2 className="mr-auto text-xl font-semibold">Tạo Agent</h2>
        </TopToolbar>
        <PersonaForm
          initial={{ name: "", body_md: "", notes: "" }}
          submitLabel="Tạo Agent"
          onSubmit={onSubmit}
        />
      </div>
    </CreateBase>
  );
};
