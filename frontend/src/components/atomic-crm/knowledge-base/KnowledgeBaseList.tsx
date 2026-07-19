import { ListBase, useListContext, useRedirect } from "ra-core";
import { BookOpen, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AlternateCard, EmptyState, PageHeading, PageShell } from "../kit";
import type { KnowledgeBase } from "../types";

const Content = () => {
  const { data = [], isPending } = useListContext<KnowledgeBase>();
  const redirect = useRedirect();

  return (
    <PageShell>
      <PageHeading
        eyebrow="Dữ liệu dùng chung"
        title="Kho kiến thức"
        subtitle="Tổ chức nguồn kiến thức để nhiều Agent và dự án cùng sử dụng."
        actions={
          <Button
            size="sm"
            onClick={() => redirect("create", "knowledge_bases")}
          >
            <Plus className="size-4" aria-hidden="true" />
            Tạo kho
          </Button>
        }
      />

      {isPending ? (
        <AlternateCard className="mt-4" bodyClassName="p-6">
          <p className="text-body-sm text-muted-foreground" role="status">
            Đang tải kho kiến thức…
          </p>
        </AlternateCard>
      ) : data.length === 0 ? (
        <AlternateCard className="mt-4">
          <EmptyState
            icon={<BookOpen className="size-6" aria-hidden="true" />}
            title="Chưa có kho kiến thức"
            description="Tạo kho đầu tiên để dùng chung dữ liệu giữa các Agent."
            action={
              <Button
                size="sm"
                onClick={() => redirect("create", "knowledge_bases")}
              >
                <Plus className="size-4" aria-hidden="true" />
                Tạo kho đầu tiên
              </Button>
            }
          />
        </AlternateCard>
      ) : (
        <div className="mt-4 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.map((kb) => (
            <Card
              key={kb.id}
              className="tt-card-sm gap-3 border-[var(--tt-border)] py-4 shadow-[var(--tt-shadow-xs)] transition-colors hover:border-[var(--tt-accent)]"
            >
              <CardHeader className="gap-1 px-4">
                <CardTitle className="text-card-title">{kb.name}</CardTitle>
                <p className="text-helper text-muted-foreground">
                  {kb.mode === "RAG" ? "RAG" : "Ngữ cảnh trực tiếp"}
                </p>
              </CardHeader>
              <CardContent className="px-4">
                <p className="text-body-sm">
                  {kb.attached_agent_count} Agent · {kb.project_count} dự án
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-3"
                  onClick={() => redirect("show", "knowledge_bases", kb.id)}
                >
                  Quản lý
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </PageShell>
  );
};

export const KnowledgeBaseList = () => (
  <ListBase
    resource="knowledge_bases"
    perPage={100}
    sort={{ field: "name", order: "ASC" }}
  >
    <Content />
  </ListBase>
);
