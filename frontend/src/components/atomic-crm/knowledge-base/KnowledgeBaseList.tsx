import { ListBase, useListContext, useRedirect } from "ra-core";
import { BookOpen, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { KnowledgeBase } from "../types";

const Content = () => {
  const { data = [], isPending } = useListContext<KnowledgeBase>();
  const redirect = useRedirect();

  return (
    <div className="mx-auto w-full max-w-[1180px] px-4 py-5 pb-24 md:px-6 md:py-6 md:pb-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-content-title font-semibold tracking-tight">
            Kho kiến thức
          </h1>
          <p className="mt-1 text-body-sm text-muted-foreground">
            Nguồn kiến thức dùng chung cho Agent.
          </p>
        </div>
        <Button
          size="sm"
          onClick={() => redirect("create", "knowledge_bases")}
        >
          <Plus className="size-4" aria-hidden="true" />
          Tạo kho
        </Button>
      </header>

      {isPending ? (
        <p className="mt-4 text-body-sm text-muted-foreground">Đang tải…</p>
      ) : data.length === 0 ? (
        <Card className="mt-3 p-8 text-center">
          <BookOpen
            className="mx-auto size-8 text-muted-foreground"
            aria-hidden="true"
          />
          <p className="mt-3 text-body font-medium">Chưa có kho kiến thức</p>
          <p className="mt-1 text-helper text-muted-foreground">
            Tạo kho đầu tiên để dùng chung dữ liệu giữa các Agent.
          </p>
        </Card>
      ) : (
        <div className="mt-3 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {data.map((kb) => (
            <Card key={kb.id} className="tt-card-sm gap-3 py-4">
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
    </div>
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
