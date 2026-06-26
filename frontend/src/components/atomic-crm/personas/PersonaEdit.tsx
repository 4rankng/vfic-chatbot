import {
  EditBase,
  useDataProvider,
  useNotify,
  useRecordContext,
  useRedirect,
  useRefresh,
} from "ra-core";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Zap } from "lucide-react";
import { TopToolbar } from "../layout/TopToolbar";
import { PersonaForm, type PersonaValues } from "./PersonaForm";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { Persona } from "../types";
import { activatePersona } from "@/lib/vfic/knowledgeService";

const PersonaEditContent = () => {
  const persona = useRecordContext<Persona>();
  const notify = useNotify();
  const redirect = useRedirect();
  const refresh = useRefresh();
  const dataProvider = useDataProvider<CrmDataProvider>();
  if (!persona) return null;

  const onSubmit = async (v: PersonaValues) => {
    try {
      await dataProvider.update("personas", {
        id: persona.id,
        previousData: persona,
        data: { name: v.name, body_md: v.body_md, notes: v.notes || null },
      });
      notify("Đã lưu.", { type: "success" });
      refresh();
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    }
  };

  const onActivate = async () => {
    try {
      await activatePersona(persona.id);
      notify("Đã kích hoạt persona.", { type: "success" });
      refresh();
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    }
  };

  return (
    <PersonaForm
      key={persona.id}
      initial={{
        name: persona.name,
        body_md: persona.body_md,
        notes: persona.notes ?? "",
      }}
      submitLabel="Lưu"
      onSubmit={onSubmit}
      extraActions={
        <>
          {persona.is_active ? (
            <Badge>Đang dùng</Badge>
          ) : (
            <Button type="button" variant="outline" onClick={onActivate}>
              <Zap className="size-4" />
              Kích hoạt
            </Button>
          )}
          <Button type="button" variant="ghost" onClick={() => redirect("/personas")}>
            Hủy
          </Button>
        </>
      }
    />
  );
};

export const PersonaEdit = () => (
  <EditBase>
    <TopToolbar>
      <h2 className="mr-auto text-xl font-semibold">Chỉnh sửa persona</h2>
    </TopToolbar>
    <PersonaEditContent />
  </EditBase>
);
