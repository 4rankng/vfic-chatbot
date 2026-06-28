import { useEffect, useState } from "react";
import { useNotify } from "ra-core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Pencil,
  RefreshCw,
  Sparkles,
  Star,
  X,
} from "lucide-react";
import {
  extractProjectFeatures,
  getProjectFeatures,
  updateProjectFeature,
} from "@/lib/vfic/knowledgeService";
import type { ProductFeature } from "../types";
import { cn } from "@/lib/utils";

// Active worker product-feature catalogue size. Migration 0009 disabled 5 white-collar /
// meta criteria for manual-labour scope, leaving 11 active rows in worker_feature_catalog.
// The gauge is positional across these slots.
const FEATURE_SLOTS = 11;

const FEATURE_CATEGORY_LABELS: Record<string, string> = {
  application: "Hồ sơ ứng tuyển",
  bonus: "Thưởng và hỗ trợ",
  cashflow: "Kỳ lương",
  commute: "Đi lại",
  daily_cost: "Phúc lợi giảm chi phí",
  housing: "Chỗ ở",
  income: "Thu nhập",
  job_difficulty: "Công việc",
  schedule: "Lịch làm việc",
};

const getFeatureCategoryLabel = (category: string | null | undefined) => {
  const key = category?.trim().toLowerCase();
  if (!key) return "Khác";
  return FEATURE_CATEGORY_LABELS[key] ?? category;
};

const normalizeFeatureText = (value: string | null | undefined) =>
  (value ?? "")
    .trim()
    .replace(/^["“”]+|["“”]+$/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();

const shouldShowEvidence = (feature: ProductFeature) => {
  const evidence = normalizeFeatureText(feature.evidence_text);
  return Boolean(
    evidence && evidence !== normalizeFeatureText(feature.value_text),
  );
};

// Binary readiness derivation. A feature is "đủ thông tin" (ready) when the
// agent has a non-empty value_text and the row is not flagged missing/unclear.
// Empty slots are NOT ready.
const isReady = (f: ProductFeature | null | undefined): boolean =>
  !!f && !!f.value_text?.trim() && !f.is_missing && !f.needs_clarification;

// Canonical 1..16 positional view: sort by the catalog display_priority and
// pad to FEATURE_SLOTS so the gauge is always positional regardless of how many
// rows the API returned.
const orderedSlots = (
  features: ProductFeature[] | null,
): (ProductFeature | null)[] => {
  const sorted = [...(features ?? [])].sort(
    (a, b) => a.display_priority - b.display_priority,
  );
  const slots: (ProductFeature | null)[] = [];
  for (let i = 0; i < FEATURE_SLOTS; i++) slots.push(sorted[i] ?? null);
  return slots;
};

// "Đặc điểm sản phẩm" panel: the 11 active worker product features extracted from the
// project's posting. Reframed as a per-project readiness view: across the active catalog
// features, whether the agent has enough info to advise on each criterion, or needs more.
export const ProjectFeatures = ({
  projectId,
  editable = false,
}: {
  projectId: string;
  editable?: boolean;
}) => {
  const notify = useNotify();
  const [features, setFeatures] = useState<ProductFeature[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [showDetail, setShowDetail] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await getProjectFeatures(projectId);
      setFeatures(res.data);
    } catch (err) {
      notify(`Không tải được đặc điểm: ${(err as Error).message}`, {
        type: "error",
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const onExtract = async () => {
    setExtracting(true);
    try {
      const res = await extractProjectFeatures(projectId);
      setFeatures(res.data);
      notify("Đã trích xuất 11 đặc điểm sản phẩm.", { type: "success" });
    } catch (err) {
      notify(`Trích xuất thất bại: ${(err as Error).message}`, {
        type: "error",
      });
    } finally {
      setExtracting(false);
    }
  };

  const onUpdate = (updated: ProductFeature) => {
    setFeatures((prev) =>
      (prev ?? []).map((f) => (f.id === updated.id ? updated : f)),
    );
  };

  const slots = orderedSlots(features);
  const readySlots = slots.filter(isReady);
  const gapSlots = slots.filter((s) => !isReady(s));
  const readyCount = readySlots.length;
  const gapCount = FEATURE_SLOTS - readyCount;
  const hasFeatures = (features?.length ?? 0) > 0;

  // Detailed editable cards stay category-grouped inside the disclosure (cleaner
  // for 16-card grids), but the collapsed summary is the binary hero above it.
  const groupedFeatures = (features ?? []).reduce<
    Record<string, ProductFeature[]>
  >((acc, feature) => {
    const key = getFeatureCategoryLabel(feature.category);
    acc[key] = acc[key] ?? [];
    acc[key].push(feature);
    return acc;
  }, {});

  return (
    <Card className="mt-0 overflow-hidden">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-base">
          <span>Đặc điểm sản phẩm</span>
          {editable && hasFeatures && (
            <Button
              variant="outline"
              size="sm"
              onClick={onExtract}
              disabled={extracting}
              title="Trích xuất lại 11 đặc điểm từ tin tuyển dụng (chạy LLM, ~5-10s)"
            >
              <Sparkles className="size-4" />
              {extracting ? "Đang trích xuất..." : "Trích xuất lại"}
            </Button>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 pt-2">
        {loading ? (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : (
          <>
            <ReadinessHero readyCount={readyCount} extracting={extracting} />

            {hasFeatures ? (
              <div className="space-y-3">
                <FeatureGroup
                  tone="ready"
                  count={readyCount}
                  slots={readySlots}
                />
                <FeatureGroup tone="gap" count={gapCount} slots={gapSlots} />

                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full justify-center border border-dashed text-xs text-muted-foreground"
                  onClick={() => setShowDetail((s) => !s)}
                  aria-expanded={showDetail}
                >
                  <ChevronDown
                    className={cn(
                      "size-4 transition-transform",
                      showDetail && "rotate-180",
                    )}
                  />
                  {showDetail
                    ? "Thu gọn"
                    : editable
                      ? "Xem chi tiết & chỉnh sửa"
                      : "Xem chi tiết"}
                </Button>
                {showDetail && (
                  <div className="space-y-4">
                    {Object.entries(groupedFeatures).map(
                      ([category, items]) => (
                        <section key={category} className="space-y-2">
                          <div className="flex items-center justify-between gap-2">
                            <h3 className="text-sm font-semibold">
                              {category}
                            </h3>
                            <span className="text-xs text-muted-foreground">
                              {items.length} mục
                            </span>
                          </div>
                          <div className="grid gap-3 lg:grid-cols-2">
                            {items.map((f) => (
                              <FeatureCard
                                key={f.id}
                                projectId={projectId}
                                feature={f}
                                editable={editable}
                                onUpdate={onUpdate}
                              />
                            ))}
                          </div>
                        </section>
                      ),
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3 rounded-md bg-muted/40 p-5 text-center text-muted-foreground">
                <RefreshCw className="size-5 opacity-50" />
                <p className="text-sm font-medium">Chưa có đặc điểm sản phẩm</p>
                <p className="text-xs">
                  {editable
                    ? 'Tải tin tuyển dụng lên rồi bấm "Trích xuất lại" để LLM trích 11 đặc điểm.'
                    : "Dự án này chưa có đặc điểm sản phẩm để hiển thị."}
                </p>
                {editable && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onExtract}
                    disabled={extracting}
                    title="Trích xuất lại 11 đặc điểm từ tin tuyển dụng (chạy LLM, ~5-10s)"
                  >
                    <Sparkles className="size-4" />
                    {extracting ? "Đang trích xuất..." : "Trích xuất lại"}
                  </Button>
                )}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
};

// Readiness hero: "{n}/11 CÓ THỂ TƯ VẤN" + an indeterminate-pulsing bar while
// the LLM extract is in flight. We do NOT fake sequential ticks over the real
// ~5-10s call.
const ReadinessHero = ({
  readyCount,
  extracting,
}: {
  readyCount: number;
  extracting: boolean;
}) => {
  const pct = Math.round((readyCount / FEATURE_SLOTS) * 100);
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono uppercase tracking-wide text-muted-foreground">
          Sẵn sàng tư vấn
        </span>
        <span className="text-sm font-semibold tabular-nums">
          {readyCount}/{FEATURE_SLOTS} có thể tư vấn
        </span>
      </div>
      {/* Decorative bar — the visible "{n}/11 có thể tư vấn" text above is the
          canonical label; the gap count is announced by the group headings below. */}
      <div
        aria-hidden="true"
        className="relative h-2.5 w-full overflow-hidden rounded-full bg-muted"
      >
        {extracting ? (
          // Indeterminate pulse — no fake sequential progress.
          <div className="absolute inset-y-0 left-0 w-1/3 animate-pulse rounded-full bg-primary/60" />
        ) : (
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-primary transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <i className="size-2.5 rounded-[3px] bg-feature-ready" />
          Đủ thông tin
        </span>
        <span className="inline-flex items-center gap-1.5">
          <i className="size-2.5 rounded-[3px] border border-feature-gap-border border-dashed bg-feature-gap-soft" />
          Cần bổ sung
        </span>
      </div>
    </div>
  );
};

// One of the two readiness groups. Highlights are NOT a separate group — a
// ready + is_highlight slot shows a small ⭐ accent next to its name.
const FeatureGroup = ({
  tone,
  count,
  slots,
}: {
  tone: "ready" | "gap";
  count: number;
  slots: (ProductFeature | null)[];
}) => {
  const ready = tone === "ready";
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold">
          {ready ? (
            <CheckCircle2 className="size-4 text-feature-ready" />
          ) : (
            <AlertCircle className="size-4 text-feature-gap" />
          )}
          {ready ? "Đủ thông tin" : "Cần bổ sung"}
        </h3>
        <span className="text-xs text-muted-foreground">{count} mục</span>
      </div>
      {count > 0 ? (
        <div className="grid gap-2 md:grid-cols-2">
          {slots.map((f, i) => {
            const name = f?.name_vi ?? "Chưa trích xuất";
            const highlighted = ready && !!f?.is_highlight;
            return (
              <div
                key={f?.id ?? `slot-${i}`}
                className={cn(
                  "flex items-center gap-2.5 rounded-md border bg-muted/20 px-2.5 py-2 text-xs",
                  ready
                    ? "border-feature-ready/30 bg-feature-ready-soft"
                    : "border-feature-gap-border border-dashed bg-feature-gap-soft",
                )}
              >
                <span
                  className={cn(
                    "h-[18px] w-1 shrink-0 rounded-full",
                    ready ? "bg-feature-ready" : "bg-feature-gap",
                  )}
                />
                <span className="flex min-w-0 flex-1 items-center gap-1 truncate text-foreground">
                  <span className="truncate">{name}</span>
                  {highlighted && (
                    <Star
                      className="size-3.5 shrink-0 text-feature-ready"
                      aria-label="Nổi bật"
                    />
                  )}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="rounded-md border border-dashed bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
          {ready
            ? "Chưa có đặc điểm đủ thông tin."
            : "Không còn mục cần bổ sung."}
        </p>
      )}
    </section>
  );
};

const FeatureCard = ({
  projectId,
  feature,
  editable,
  onUpdate,
}: {
  projectId: string;
  feature: ProductFeature;
  editable: boolean;
  onUpdate: (f: ProductFeature) => void;
}) => {
  const notify = useNotify();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(feature.value_text);
  const [highlight, setHighlight] = useState(feature.is_highlight);
  const [saving, setSaving] = useState(false);
  const showEvidence = shouldShowEvidence(feature);

  const save = async () => {
    setSaving(true);
    try {
      const updated = await updateProjectFeature(projectId, feature.id, {
        value_text: draft,
        is_highlight: highlight,
      });
      onUpdate(updated);
      setEditing(false);
      notify("Đã lưu.", { type: "success" });
    } catch (err) {
      notify(`Lưu thất bại: ${(err as Error).message}`, { type: "error" });
    } finally {
      setSaving(false);
    }
  };

  const cancel = () => {
    setDraft(feature.value_text);
    setHighlight(feature.is_highlight);
    setEditing(false);
  };

  return (
    <div
      className={cn(
        "min-w-0 rounded-md border p-3",
        feature.is_highlight && "border-feature-ready/30 bg-feature-ready-soft",
        (feature.is_missing || feature.needs_clarification) &&
          "border-feature-gap-border bg-feature-gap-soft",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="min-w-0 text-sm font-semibold">
              {feature.name_vi}
            </span>
            {feature.is_highlight && (
              <Badge className="bg-feature-ready text-[10px] text-primary-foreground">
                Nổi bật
              </Badge>
            )}
            {(feature.is_missing || feature.needs_clarification) && (
              <Badge
                variant="secondary"
                className="border border-feature-gap-border bg-feature-gap-soft text-[10px] text-feature-gap"
              >
                Chưa rõ
              </Badge>
            )}
          </div>
          {editing ? (
            <div className="mt-2 flex flex-col gap-2">
              <Textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={3}
                className="text-sm"
              />
              <label className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={highlight}
                  onChange={(e) => setHighlight(e.target.checked)}
                />
                Điểm nổi bật (hiện trong thẻ danh mục)
              </label>
            </div>
          ) : (
            <>
              <p className="mt-1 text-sm leading-5">{feature.value_text}</p>
              {showEvidence && (
                <p className="mt-1 text-xs italic text-muted-foreground">
                  "{feature.evidence_text}"
                </p>
              )}
            </>
          )}
        </div>
        {editable && editing ? (
          <div className="flex shrink-0 gap-1">
            <Button
              size="sm"
              variant="ghost"
              onClick={cancel}
              disabled={saving}
            >
              <X className="size-3.5" />
            </Button>
            <Button size="sm" onClick={save} disabled={saving}>
              {saving ? "..." : "Lưu"}
            </Button>
          </div>
        ) : editable ? (
          <Button
            size="sm"
            variant="ghost"
            className="shrink-0"
            onClick={() => setEditing(true)}
          >
            <Pencil className="size-3.5" />
          </Button>
        ) : null}
      </div>
    </div>
  );
};
