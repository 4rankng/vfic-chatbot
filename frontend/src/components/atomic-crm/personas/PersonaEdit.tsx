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
import { ArrowLeft, Bot, CheckCircle2, FileText, Zap } from "lucide-react";
import { PersonaAssignments } from "./PersonaAssignments";
import {
  getCompletedPersonaSectionCount,
  getPersonaAuthoredContentLength,
  PersonaForm,
  type PersonaValues,
} from "./PersonaForm";
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
        data: {
          name: v.name,
          body_md: v.body_md,
          notes: v.notes,
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
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5 px-4 pb-12 md:px-6 md:pb-16 lg:px-0">
      <div className="rounded-lg border bg-card/80 p-4 shadow-sm backdrop-blur-sm md:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="-ml-2 h-8 px-2 text-muted-foreground"
              onClick={() => redirect("/personas")}
            >
              <ArrowLeft className="size-4" />
              Quay lại danh sách
            </Button>
            <div className="mt-3 flex items-start gap-3">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-primary/10 text-primary">
                <Bot className="size-5" />
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-2xl font-semibold tracking-tight">
                    Chỉnh sửa Agent
                  </h1>
                  {persona.is_active && (
                    <Badge
                      variant="outline"
                      className="gap-1 border-primary/20 bg-primary/5 text-primary"
                    >
                      <CheckCircle2 className="size-3.5" />
                      Đang dùng
                    </Badge>
                  )}
                </div>
                <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                  Cập nhật vai trò, luật trả lời và phạm vi sử dụng cho Agent
                  chatbot.
                </p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:w-[360px]">
            <div className="rounded-lg border bg-background/70 p-3">
              <div className="flex items-center gap-2 text-xs font-medium uppercase text-muted-foreground">
                <FileText className="size-3.5" />
                Nội dung
              </div>
              <div className="mt-1 text-xl font-semibold tabular-nums">
                {sectionCount}/7
              </div>
            </div>
            <div className="rounded-lg border bg-background/70 p-3">
              <div className="text-xs font-medium uppercase text-muted-foreground">
                Ký tự
              </div>
              <div className="mt-1 text-xl font-semibold tabular-nums">
                {contentLength.toLocaleString("vi-VN")}
              </div>
            </div>
            <div className="col-span-2 rounded-lg border bg-background/70 p-3 sm:col-span-1">
              <div className="text-xs font-medium uppercase text-muted-foreground">
                Tên
              </div>
              <div className="mt-1 truncate text-sm font-semibold">
                {persona.name || "Chưa đặt tên"}
              </div>
            </div>
          </div>
        </div>
      </div>

      <PersonaForm
        key={persona.id}
        initial={{
          name: persona.name,
          body_md: persona.body_md,
          notes: persona.notes ?? "",
          followup_rules: persona.followup_rules,
        }}
        submitLabel="Lưu"
        onSubmit={onSubmit}
        extraActions={
          <>
            {persona.is_active ? (
              <Badge
                variant="outline"
                className="border-primary/20 bg-primary/5 text-primary"
              >
                Đang dùng
              </Badge>
            ) : (
              <Button type="button" variant="outline" onClick={onActivate}>
                <Zap className="size-4" />
                Kích hoạt
              </Button>
            )}
            <Button
              type="button"
              variant="ghost"
              onClick={() => redirect("/personas")}
            >
              Hủy
            </Button>
          </>
        }
      />
      <PersonaAssignments persona={persona} />
    </div>
  );
};

export const PersonaEdit = () => (
  <EditBase>
    <PersonaEditContent />
  </EditBase>
);
