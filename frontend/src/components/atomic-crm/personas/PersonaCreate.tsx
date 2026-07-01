import { CreateBase, useDataProvider, useNotify, useRedirect } from "ra-core";
import { useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TopToolbar } from "../layout/TopToolbar";
import { PersonaForm, type PersonaValues } from "./PersonaForm";
import type { CrmDataProvider } from "../providers/rest/dataProvider";

export const PersonaCreate = () => {
  const notify = useNotify();
  const redirect = useRedirect();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const navigate = useNavigate();

  const onSubmit = async (v: PersonaValues) => {
    try {
      await dataProvider.create("personas", {
        data: {
          name: v.name,
          body_md: v.body_md,
          notes: v.notes || null,
          followup_rules: v.followup_rules,
        },
      });
      notify("Đã tạo Agent.", { type: "success" });
      redirect("/personas");
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    }
  };

  return (
    <CreateBase resource="personas">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-5 px-4 pb-12 md:px-6 md:pb-16 lg:px-0">
        <TopToolbar className="flex-col items-start justify-start gap-2">
          <Button
            variant="ghost"
            size="sm"
            className="-ml-2 text-muted-foreground"
            onClick={() => navigate("/personas")}
          >
            <ArrowLeft className="size-4" />
            Quay lại
          </Button>
          <div className="max-w-2xl">
            <h2 className="text-2xl font-semibold tracking-tight">Tạo Agent</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Soạn vai trò, luật trả lời và hướng dẫn vận hành cho chatbot.
            </p>
          </div>
        </TopToolbar>
        <PersonaForm
          initial={{
            name: "",
            body_md: "",
            notes: "",
            followup_rules: undefined,
          }}
          submitLabel="Tạo Agent"
          onSubmit={onSubmit}
          onImported={() => redirect("/personas")}
        />
      </div>
    </CreateBase>
  );
};
