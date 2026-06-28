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

// The fixed worker product-feature catalogue size (see migration 0004:
// worker_feature_catalog). The gauge is positional across these slots.
const FEATURE_SLOTS = 16;

type FeatureState = "data" | "highlight" | "gap" | "empty";

const STATE_LABEL_VI: Record<FeatureState, string> = {
  data: "Đã có dữ liệu",
  highlight: "Nổi bật",
  gap: "Cần bổ sung",
  empty: "Chưa trích xuất",
};

// Derive a tick state from a feature row. Highlight wins over gap (a standout
// is a standout even if imperfect); a missing/unclear row is a gap; otherwise
// the slot has data. An absent row (catalog slot not yet filled) is empty.
const featureState = (f: ProductFeature | null | undefined): FeatureState => {
  if (!f) return "empty";
  if (f.is_highlight) return "highlight";
  if (f.is_missing || f.needs_clarification) return "gap";
  return "data";
};

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

const tickClass = (state: FeatureState): string =>
  state === "data"
    ? "border-emerald-500 bg-emerald-500"
    : state === "highlight"
      ? "border-primary bg-primary"
      : state === "gap"
        ? "border-destructive border-dashed bg-destructive/10"
        : "border-border bg-muted";

// "Đặc điểm sản phẩm" panel: the 16 worker product features extracted from the project's
// posting. Admin can re-extract (sync MiniMax call, persona pattern) and inline-edit each
// value. Mirrors the agent's get_product_features tool output.
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
      notify("Đã trích xuất 16 đặc điểm sản phẩm.", { type: "success" });
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
  const states = slots.map(featureState);
  const dataCount = states.filter(
    (s) => s === "data" || s === "highlight",
  ).length;
  const highlightCount = states.filter((s) => s === "highlight").length;
  const gapCount = states.filter((s) => s === "gap").length;
  const completion = Math.round((dataCount / FEATURE_SLOTS) * 100);
  const hasFeatures = (features?.length ?? 0) > 0;
  const groupedFeatures = (features ?? []).reduce<
    Record<string, ProductFeature[]>
  >((acc, feature) => {
    const key = feature.category || "Khác";
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
              title="Trích xuất lại 16 đặc điểm từ tin tuyển dụng (chạy LLM, ~5-10s)"
            >
              <Sparkles className="size-4" />
              {extracting ? "Đang trích xuất..." : "Trích xuất lại"}
            </Button>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 pt-2">
        <div className="grid gap-3 sm:grid-cols-3">
          <FeatureStat
            icon={<CheckCircle2 className="size-4" />}
            label="Đã có dữ liệu"
            value={`${dataCount}/${FEATURE_SLOTS}`}
          />
          <FeatureStat
            icon={<Star className="size-4" />}
            label="Nổi bật"
            value={String(highlightCount)}
          />
          <FeatureStat
            icon={<AlertCircle className="size-4" />}
            label="Cần bổ sung"
            value={String(gapCount)}
          />
        </div>
        {loading ? (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : (
          <>
            <FeatureGauge
              slots={slots}
              states={states}
              dataCount={dataCount}
              highlightCount={highlightCount}
              gapCount={gapCount}
              completion={completion}
              extracting={extracting}
            />

            {hasFeatures ? (
              <div className="space-y-3">
                <FeatureLegendGrid slots={slots} states={states} />
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
                          <div className="grid gap-2 xl:grid-cols-2">
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
                    ? 'Tải tin tuyển dụng lên rồi bấm "Trích xuất lại" để LLM trích 16 đặc điểm.'
                    : "Dự án này chưa có đặc điểm sản phẩm để hiển thị."}
                </p>
                {editable && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onExtract}
                    disabled={extracting}
                    title="Trích xuất lại 16 đặc điểm từ tin tuyển dụng (chạy LLM, ~5-10s)"
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

// Signature 16-tick positional gauge. Each tick maps to one catalog slot in
// display_priority order; colour encodes the slot's state. While the LLM
// extract is in flight, all ticks pulse indeterminate — we do not fake
// sequential progress over the real ~5-10s call.
const FeatureGauge = ({
  slots,
  states,
  dataCount,
  highlightCount,
  gapCount,
  completion,
  extracting,
}: {
  slots: (ProductFeature | null)[];
  states: FeatureState[];
  dataCount: number;
  highlightCount: number;
  gapCount: number;
  completion: number;
  extracting: boolean;
}) => {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="font-mono uppercase tracking-wide text-muted-foreground">
          Bộ 16 đặc điểm
        </span>
        <span className="font-medium tabular-nums">
          {dataCount}/{FEATURE_SLOTS} · {completion}%
        </span>
      </div>
      <div className="flex items-center gap-1">
        <span className="w-4 shrink-0 text-center font-mono text-[10px] text-muted-foreground">
          01
        </span>
        <div
          className="flex flex-1 gap-1"
          role="img"
          aria-label={`16 đặc điểm: ${dataCount} đã có dữ liệu, ${highlightCount} nổi bật, ${gapCount} cần bổ sung`}
        >
          {slots.map((f, i) => {
            const state = states[i];
            const label = `${String(i + 1).padStart(2, "0")}${f ? ` · ${f.name_vi}` : ""} · ${STATE_LABEL_VI[state]}`;
            return (
              <span
                key={i}
                title={label}
                className={cn(
                  "h-[26px] min-w-[14px] flex-1 rounded-[3px] border transition-colors",
                  extracting
                    ? "animate-pulse border-border bg-muted"
                    : tickClass(state),
                )}
              />
            );
          })}
        </div>
        <span className="w-4 shrink-0 text-center font-mono text-[10px] text-muted-foreground">
          16
        </span>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-[11px] text-muted-foreground">
        <LegendSwatch swatchClass="bg-emerald-500" label="Đã có dữ liệu" />
        <LegendSwatch swatchClass="bg-primary" label="Nổi bật" />
        <LegendSwatch
          swatchClass="border-destructive border-dashed bg-destructive/10"
          label="Cần bổ sung"
        />
        <LegendSwatch
          swatchClass="border border-border bg-muted"
          label="Chưa trích xuất"
        />
      </div>
    </div>
  );
};

const LegendSwatch = ({
  swatchClass,
  label,
}: {
  swatchClass: string;
  label: string;
}) => (
  <span className="inline-flex items-center gap-1.5">
    <i className={cn("size-2.5 rounded-[3px]", swatchClass)} />
    {label}
  </span>
);

// Compact at-a-glance index: one row per slot, bridging the abstract gauge and
// the detailed editable cards behind the disclosure toggle.
const FeatureLegendGrid = ({
  slots,
  states,
}: {
  slots: (ProductFeature | null)[];
  states: FeatureState[];
}) => (
  <div className="grid gap-2 xl:grid-cols-2">
    {slots.map((f, i) => {
      const state = states[i];
      return (
        <div
          key={f?.id ?? `slot-${i}`}
          className="flex items-center gap-2.5 rounded-md border bg-muted/20 px-2.5 py-2 text-xs"
        >
          <span className="font-mono text-[10px] text-muted-foreground">
            {String(i + 1).padStart(2, "0")}
          </span>
          <span
            className={cn(
              "h-[18px] w-1 shrink-0 rounded-full",
              state === "data" && "bg-emerald-500",
              state === "highlight" && "bg-primary",
              state === "gap" && "bg-destructive",
              state === "empty" && "bg-border",
            )}
          />
          <span className="flex-1 truncate text-foreground">
            {f?.name_vi ?? "—"}
          </span>
          {state === "highlight" ? (
            <Star className="size-3.5 text-primary" />
          ) : state === "gap" ? (
            <AlertCircle className="size-3.5 text-destructive" />
          ) : state === "data" ? (
            <CheckCircle2 className="size-3.5 text-emerald-500" />
          ) : null}
        </div>
      );
    })}
  </div>
);

const FeatureStat = ({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) => (
  <div className="rounded-md border bg-muted/20 p-3">
    <div className="flex items-center justify-between gap-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-muted-foreground">{icon}</span>
    </div>
    <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
  </div>
);

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
        "rounded-md border p-3",
        feature.is_highlight && "border-emerald-200 bg-emerald-50",
        (feature.is_missing || feature.needs_clarification) &&
          "border-destructive/30 bg-destructive/5",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-sm font-semibold">{feature.name_vi}</span>
            {feature.is_highlight && (
              <Badge className="bg-emerald-500 text-[10px]">Nổi bật</Badge>
            )}
            {(feature.is_missing || feature.needs_clarification) && (
              <Badge variant="secondary" className="text-[10px]">
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
              {feature.evidence_text && (
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
