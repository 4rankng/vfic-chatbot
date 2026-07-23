import { ShowBase, useGetOne, useRecordContext, useRedirect } from "ra-core";
import { ArrowLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { KnowledgeSource, Project } from "../types";
import { TopToolbar } from "../layout/TopToolbar";
import { KnowledgeDetailPanel } from "./KnowledgeDetailPanel";
import "../conversations/inbox.css";

const KnowledgeSourceShowContent = () => {
  const source = useRecordContext<KnowledgeSource>();
  const redirect = useRedirect();
  const projectId = source?.project_id ?? "";
  const { data: project } = useGetOne<Project>(
    "projects",
    { id: projectId },
    { enabled: projectId !== "" },
  );

  if (!source) return null;

  return (
    <section
      className="kb-scope knowledge-source-subpage"
      aria-label="Chi tiết nguồn kiến thức"
    >
      <TopToolbar className="knowledge-source-subpage-toolbar justify-start">
        <Button
          type="button"
          variant="ghost"
          className="tt-btn-touch h-11 rounded-[9px]"
          onClick={() => redirect("list", "knowledge_sources")}
        >
          <ArrowLeft className="size-4" />
          Tất cả nguồn
        </Button>
      </TopToolbar>

      <KnowledgeDetailPanel
        source={source}
        project={project}
        headingId="knowledge-source-page-title"
        headingAs="h1"
      />
    </section>
  );
};

export const KnowledgeSourceShow = () => (
  <ShowBase>
    <KnowledgeSourceShowContent />
  </ShowBase>
);
