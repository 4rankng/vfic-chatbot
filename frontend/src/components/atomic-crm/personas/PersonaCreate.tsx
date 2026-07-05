import { CreateBase, useDataProvider, useNotify, useRedirect } from "ra-core";
import { useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PersonaForm, type PersonaValues } from "./PersonaForm";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import { PersonaWorkspaceShell } from "./PersonaWorkspaceShell";

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
      <PersonaWorkspaceShell>
        <div className="persona-workspace-content">
          <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
            <header className="persona-editor-header persona-create-header">
              <Button
                variant="ghost"
                size="sm"
                className="persona-create-back"
                onClick={() => navigate("/personas")}
              >
                <ArrowLeft className="size-4" />
                Quay lại
              </Button>
              <div className="persona-create-heading">
                <h1>Tạo Agent</h1>
                <p>Nhập file cấu hình hoặc viết prompt thủ công cho chatbot.</p>
              </div>
            </header>
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
        </div>
      </PersonaWorkspaceShell>
    </CreateBase>
  );
};
