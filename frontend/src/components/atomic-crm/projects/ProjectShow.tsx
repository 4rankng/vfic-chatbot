import {
  ShowBase,
  usePermissions,
  useRecordContext,
  useRedirect,
} from "ra-core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Pencil } from "lucide-react";
import { TopToolbar } from "../layout/TopToolbar";
import type { Project } from "../types";
import { ProjectFeatures } from "./ProjectFeatures";
import { DeleteButton } from "@/components/admin";

const ProjectShowContent = () => {
  const project = useRecordContext<Project>();
  const redirect = useRedirect();
  const { permissions } = usePermissions();
  if (!project) return null;

  const card = project.index_card ?? {};
  const isAdmin = permissions === "admin";

  return (
    <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
      <Card className="h-fit">
        <CardHeader>
          <CardTitle className="flex items-center justify-between gap-2 text-base">
            <span>{project.name}</span>
            <Badge
              variant="outline"
              className={
                project.is_active
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                  : "border-border bg-muted/40 text-muted-foreground"
              }
            >
              {project.is_active ? "Đang hoạt động" : "Tắt"}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <div>
            <div className="text-xs uppercase tracking-wide text-muted-foreground">
              Mã dự án
            </div>
            <div className="font-mono">{project.slug}</div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wide text-muted-foreground">
              Tóm tắt
            </div>
            <p>{project.summary ?? "—"}</p>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wide text-muted-foreground">
              Địa điểm
            </div>
            <p>{card.location ?? "—"}</p>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wide text-muted-foreground">
              Vị trí
            </div>
            <p>{(card.key_roles ?? []).join(", ") || "—"}</p>
          </div>
          {isAdmin && (
            <div className="mt-1 flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                className="w-fit"
                onClick={() => redirect("edit", "projects", project.id)}
              >
                <Pencil className="size-4" />
                Quản lý dự án
              </Button>
              <DeleteButton
                label="Xóa"
                size="sm"
                successMessage="Đã xóa dự án."
                redirect="list"
              />
            </div>
          )}
        </CardContent>
      </Card>

      <ProjectFeatures projectId={project.id} />
    </div>
  );
};

export const ProjectShow = () => (
  <ShowBase>
    <TopToolbar>
      <h2 className="mr-auto text-xl font-semibold">Đặc điểm dự án</h2>
    </TopToolbar>
    <ProjectShowContent />
  </ShowBase>
);
