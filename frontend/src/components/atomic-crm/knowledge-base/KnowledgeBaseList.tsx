import { ListBase, useListContext, useRedirect } from "ra-core";
import { BookOpen, ChevronRight, Plus } from "lucide-react";
import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";
import { EmptyState, PageHeading, PageShell } from "../kit";
import type { KnowledgeBase } from "../types";

export const KnowledgeBaseListContent = () => {
  const { data = [], isPending } = useListContext<KnowledgeBase>();
  const redirect = useRedirect();

  return (
    <PageShell>
      <PageHeading
        eyebrow="Dữ liệu dùng chung"
        title="Kho kiến thức"
        subtitle="Chia sẻ nguồn giữa Agent và dự án."
        actions={
          <Button
            size="sm"
            iconLeading={Plus}
            onClick={() => redirect("create", "knowledge_bases")}
          >
            Tạo kho
          </Button>
        }
      />

      <section
        className="mt-4 border-y border-[var(--workspace-border)] bg-[var(--workspace-surface)]"
        aria-labelledby="knowledge-base-list-title"
      >
        <header className="flex min-h-14 items-center justify-between gap-3 border-b border-[var(--workspace-border)] px-4 py-3">
          <h2
            id="knowledge-base-list-title"
            className="text-section-title font-semibold text-[var(--workspace-ink)]"
          >
            Kho hiện có
          </h2>
          {!isPending && data.length > 0 ? (
            <span
              className="text-helper tabular-nums text-[var(--workspace-ink-muted)]"
              aria-label={`${data.length} kho`}
            >
              {data.length}
            </span>
          ) : null}
        </header>

        {isPending ? (
          <p
            className="px-4 py-6 text-body-sm text-[var(--workspace-ink-muted)]"
            role="status"
          >
            Đang tải kho kiến thức…
          </p>
        ) : data.length === 0 ? (
          <EmptyState
            icon={<BookOpen className="size-6" aria-hidden="true" />}
            title="Chưa có kho kiến thức"
            description="Tạo kho đầu tiên để chia sẻ dữ liệu."
            action={
              <Button
                size="sm"
                iconLeading={Plus}
                onClick={() => redirect("create", "knowledge_bases")}
              >
                Tạo kho đầu tiên
              </Button>
            }
          />
        ) : (
          <div role="list">
            {data.map((kb) => {
              const modeLabel =
                kb.mode === "RAG" ? "RAG" : "Ngữ cảnh trực tiếp";
              return (
                <div
                  key={kb.id}
                  role="listitem"
                  className="border-b border-[var(--workspace-border)] last:border-b-0"
                >
                  <button
                    type="button"
                    className="flex min-h-16 w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-[var(--workspace-surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--workspace-focus)]"
                    aria-label={`Mở kho ${kb.name}: ${modeLabel}, ${kb.attached_agent_count} Agent, ${kb.project_count} dự án`}
                    onClick={() => redirect("show", "knowledge_bases", kb.id)}
                  >
                    <BookOpen
                      className="size-5 shrink-0 text-[var(--workspace-ink-muted)]"
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="truncate text-body font-semibold text-[var(--workspace-ink)]">
                          {kb.name}
                        </span>
                        {/* Untitled UI primitive. `uu-scope` is required: it
                            re-binds the four utility names this console and
                            Untitled UI both define. See
                            src/styles/untitledui-theme.css. */}
                        <Badge
                          color="gray"
                          size="sm"
                          className="uu-scope font-semibold tracking-wide uppercase"
                        >
                          {modeLabel}
                        </Badge>
                      </span>
                      <span className="mt-1 block text-helper text-[var(--workspace-ink-muted)]">
                        {kb.attached_agent_count} Agent · {kb.project_count} dự
                        án
                      </span>
                    </span>
                    <ChevronRight
                      className="size-4 shrink-0 text-[var(--workspace-ink-muted)]"
                      aria-hidden="true"
                    />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </PageShell>
  );
};

export const KnowledgeBaseList = () => (
  <ListBase
    resource="knowledge_bases"
    perPage={100}
    sort={{ field: "name", order: "ASC" }}
  >
    <KnowledgeBaseListContent />
  </ListBase>
);
