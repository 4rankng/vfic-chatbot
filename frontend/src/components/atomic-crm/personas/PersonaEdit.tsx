import {
  EditBase,
  useDataProvider,
  useNotify,
  useRecordContext,
  useRedirect,
  useRefresh,
  useTranslate,
} from "ra-core";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  ArrowLeft,
  BotMessageSquare,
  CheckCircle2,
  FileText,
  Zap,
} from "lucide-react";
import { PersonaAssignments } from "./PersonaAssignments";
import { PersonaForm, type PersonaValues } from "./PersonaForm";
import {
  getCompletedPersonaSectionCount,
  getPersonaAuthoredContentLength,
} from "./domain/personaMarkdown";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { Persona } from "../types";
import { activatePersona } from "./personaService";
import { PersonaWorkspaceShell } from "./PersonaWorkspaceShell";

const PersonaEditContent = () => {
  const persona = useRecordContext<Persona>();
  const notify = useNotify();
  const translate = useTranslate();
  const redirect = useRedirect();
  const refresh = useRefresh();
  const dataProvider = useDataProvider<CrmDataProvider>();
  if (!persona) return null;

  const onSubmit = async (v: PersonaValues) => {
    try {
      await dataProvider.update("personas", {
        id: persona.id,
        previousData: persona,
        data: {
          name: v.name,
          body_md: v.body_md,
          notes: v.notes,
          knowledge_base_id: v.knowledge_base_id,
          followup_rules: v.followup_rules,
        },
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
      notify("Đã kích hoạt Agent.", { type: "success" });
      refresh();
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    }
  };

  const sectionCount = getCompletedPersonaSectionCount(persona.body_md);
  const contentLength = getPersonaAuthoredContentLength(persona.body_md);

  return (
    <PersonaWorkspaceShell>
      <div className="persona-workspace-content">
        <div className="persona-editor-shell">
          <header className="persona-editor-hero">
            <div className="persona-editor-hero-main">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="persona-editor-back"
                onClick={() => redirect("/personas")}
              >
                <ArrowLeft className="size-4" />
                Hồ sơ Agent
              </Button>
              <div className="persona-editor-title-row">
                <div className="persona-editor-mark" aria-hidden="true">
                  <BotMessageSquare className="size-5" />
                </div>
                <div className="min-w-0">
                  <div className="persona-editor-heading-line">
                    <h1>Chỉnh sửa Agent</h1>
                    {persona.is_active && (
                      <Badge
                        variant="outline"
                        className="persona-studio-badge is-good"
                      >
                        <CheckCircle2 className="size-3.5" />
                        Đang bật
                      </Badge>
                    )}
                  </div>
                  <p>Giọng trả lời, follow-up và kênh sử dụng.</p>
                </div>
              </div>
            </div>

            <div className="persona-editor-status-strip">
              <div>
                <span>
                  <FileText className="size-3.5" />
                  Nội dung
                </span>
                <strong>{sectionCount}/7</strong>
              </div>
              <div>
                <span>Ký tự</span>
                <strong>{contentLength.toLocaleString("vi-VN")}</strong>
              </div>
              <div>
                <span>Tên</span>
                <strong>{persona.name || "Chưa đặt tên"}</strong>
              </div>
            </div>
          </header>

          <PersonaForm
            key={persona.id}
            initial={{
              name: persona.name,
              body_md: persona.body_md,
              notes: persona.notes ?? "",
              knowledge_base_id: persona.knowledge_base_id ?? "",
              followup_rules: persona.followup_rules,
            }}
            submitLabel={translate("ra.action.save")}
            onSubmit={onSubmit}
            extraActions={
              <>
                {!persona.is_active ? (
                  <Button
                    type="button"
                    variant="outline"
                    className="tt-btn-touch"
                    onClick={onActivate}
                  >
                    <Zap className="size-4" />
                    Kích hoạt
                  </Button>
                ) : null}
                <Button
                  type="button"
                  variant="ghost"
                  className="tt-btn-touch"
                  onClick={() => redirect("/personas")}
                >
                  {translate("ra.action.cancel")}
                </Button>
              </>
            }
          />
          <PersonaAssignments persona={persona} />
        </div>
      </div>
    </PersonaWorkspaceShell>
  );
};

export const PersonaEdit = () => (
  <EditBase>
    <PersonaEditContent />
  </EditBase>
);
