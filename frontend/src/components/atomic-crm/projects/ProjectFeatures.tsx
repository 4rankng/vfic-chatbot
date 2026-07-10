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
  Sparkles,
  X,
} from "lucide-react";
import {
  extractProjectFeatures,
  getProjectFeatures,
  updateProjectFeature,
} from "@/lib/vfic/knowledgeService";
import type { ProductFeature } from "../types";
import { cn } from "@/lib/utils";
import "./projects.css";

const FEATURE_CATEGORY_LABELS: Record<string, string> = {
  application: "Hồ sơ ứng tuyển",
  bonus: "Thưởng và hỗ trợ",
  cashflow: "Kỳ lương",
  contact: "Thông tin liên lạc",
  commute: "Đi lại",
  daily_cost: "Phúc lợi giảm chi phí",
  housing: "Chỗ ở",
  income: "Thu nhập",
  job_difficulty: "Công việc",
  schedule: "Lịch làm việc",
};

const FEATURE_FILL_HINTS: Record<string, string> = {
  application_simplicity:
    "Nhập danh sách giấy tờ cần chuẩn bị và ai hỗ trợ làm hồ sơ.",
  commute_support:
    "Nhập tuyến/khu vực có xe đưa đón, mức hỗ trợ vé xe, hoặc điều kiện khoảng cách.",
  daily_cost_benefits:
    "Nhập các khoản hỗ trợ ăn ở, đi lại, ký túc xá hoặc chi phí sinh hoạt.",
  housing:
    "Nhập có/không có ký túc xá, điều kiện phòng ở, chi phí và đối tượng được ở.",
  job_difficulty:
    "Nhập công việc hằng ngày, yêu cầu kinh nghiệm, đào tạo và mức độ vất vả.",
  joining_bonus: "Nhập mức thưởng, thời điểm nhận và điều kiện để được thưởng.",
  overtime_rate:
    "Nhập cách tính tiền tăng ca theo ngày thường, ngày nghỉ và ngày lễ.",
  pay_frequency:
    "Nhập lịch trả lương, có lương tuần/ứng lương hay không, và ngày nhận tiền.",
  salary_transparency:
    "Nhập lương cơ bản, từng khoản phụ cấp, thưởng, khấu trừ và điều kiện nhận.",
  shift_schedule: "Nhập ca làm, giờ làm, ngày nghỉ, xoay ca hay cố định.",
  take_home_income:
    "Nhập tổng thu nhập thực nhận dự kiến theo tháng sau phụ cấp, tăng ca và khấu trừ.",
  contact_info:
    "Nhập người liên hệ, số điện thoại/Zalo hỗ trợ và trường hợp nào cần chuyển cho nhân viên VFIC.",
};

const getFeatureCategoryLabel = (category: string | null | undefined) => {
  const key = category?.trim().toLowerCase();
  if (!key) return "Khác";
  return FEATURE_CATEGORY_LABELS[key] ?? category;
};

const getFillHint = (feature: ProductFeature) =>
  FEATURE_FILL_HINTS[feature.feature_key] ??
  feature.worker_question_vi ??
  `Nhập thông tin cụ thể cho ${feature.name_vi}.`;

// Binary readiness derivation. A feature is "đủ thông tin" (ready) when the
// agent has a non-empty value_text and the row is not flagged missing/unclear.
// Empty slots are NOT ready.
const isReady = (f: ProductFeature | null | undefined): boolean =>
  !!f && !!f.value_text?.trim() && !f.is_missing && !f.needs_clarification;

// Canonical positional view: sort by the catalog display_priority and pad to
// the active catalog total returned by the API.
const orderedSlots = (
  features: ProductFeature[] | null,
  totalSlots: number,
): (ProductFeature | null)[] => {
  const sorted = [...(features ?? [])].sort(
    (a, b) => a.display_priority - b.display_priority,
  );
  const slots: (ProductFeature | null)[] = [];
  for (let i = 0; i < totalSlots; i++) slots.push(sorted[i] ?? null);
  return slots;
};

// "Đặc điểm sản phẩm" panel: active worker product features extracted from the
// project's posting, including missing rows that need an admin-provided value.
export const ProjectFeatures = ({
  projectId,
  editable = false,
  canExtract = editable,
  extraContent,
}: {
  projectId: string;
  editable?: boolean;
  canExtract?: boolean;
  extraContent?: React.ReactNode;
}) => {
  const notify = useNotify();
  const [features, setFeatures] = useState<ProductFeature[] | null>(null);
  const [featureTotal, setFeatureTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [showDetail, setShowDetail] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await getProjectFeatures(projectId);
      setFeatures(res.data);
      setFeatureTotal(res.total);
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
      setFeatureTotal(res.total);
      notify(`Đã trích xuất ${res.total} đặc điểm sản phẩm.`, {
        type: "success",
      });
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

  const totalSlots = Math.max(featureTotal, features?.length ?? 0);
  const slots = orderedSlots(features, totalSlots);
  const readySlots = slots.filter(isReady);
  const gapSlots = slots.filter((s) => !isReady(s));
  const readyCount = readySlots.length;
  const gapCount = Math.max(0, totalSlots - readyCount);
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
    <Card className="project-features-card mt-0 overflow-hidden">
      <CardHeader className="project-features-header">
        <CardTitle className="project-features-title flex flex-wrap items-center justify-between gap-2">
          <span>Đặc điểm sản phẩm</span>
          {canExtract && hasFeatures && (
            <Button
              variant="outline"
              size="sm"
              onClick={onExtract}
              disabled={extracting}
              className="project-feature-extract h-9"
              title="Trích xuất lại các đặc điểm từ tin tuyển dụng (chạy LLM, ~5-10s)"
            >
              <Sparkles className="size-4" />
              {extracting ? "Đang trích xuất" : "Trích xuất"}
            </Button>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="project-features-content flex flex-col gap-4 pt-2">
        {loading ? (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : (
          <>
            <ReadinessHero
              readyCount={readyCount}
              totalSlots={totalSlots}
              extracting={extracting}
            />

            {hasFeatures ? (
              <div className="space-y-3">
                {gapCount > 0 ? (
                  <>
                    <FeatureGroup
                      tone="gap"
                      count={gapCount}
                      slots={gapSlots}
                    />
                    <FeatureGroup
                      tone="ready"
                      count={readyCount}
                      slots={readySlots}
                    />
                  </>
                ) : (
                  <>
                    <FeatureGroup
                      tone="ready"
                      count={readyCount}
                      slots={readySlots}
                    />
                    <FeatureGroup
                      tone="gap"
                      count={gapCount}
                      slots={gapSlots}
                    />
                  </>
                )}

                <Button
                  variant="ghost"
                  size="sm"
                  className="project-feature-detail-toggle h-10 w-full justify-center border border-dashed text-xs text-muted-foreground"
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
                    <div className="columns-1 gap-4 xl:columns-2">
                      {Object.entries(groupedFeatures).map(
                        ([category, items]) => (
                          <section
                            key={category}
                            className="mb-4 break-inside-avoid space-y-2"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <h3 className="text-sm font-semibold">
                                {category}
                              </h3>
                              <span className="text-xs text-muted-foreground">
                                {items.length} mục
                              </span>
                            </div>
                            <div className="grid gap-3">
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
                    {extraContent && (
                      <div className="border-t pt-4">{extraContent}</div>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3 rounded-md bg-muted/40 p-5 text-center text-muted-foreground">
                <Sparkles className="size-5 opacity-50" />
                <p className="text-sm font-medium">Chưa có đặc điểm sản phẩm</p>
                <p className="text-xs">
                  {editable
                    ? "Chưa có đặc điểm sản phẩm để chỉnh sửa."
                    : "Dự án này chưa có đặc điểm sản phẩm để hiển thị."}
                </p>
                {canExtract && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onExtract}
                    disabled={extracting}
                    className="h-11"
                    title="Trích xuất lại các đặc điểm từ tin tuyển dụng (chạy LLM, ~5-10s)"
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

// Readiness hero: "{n}/{total} CÓ THỂ TƯ VẤN" + an indeterminate-pulsing bar
// while the LLM extract is in flight.
const ReadinessHero = ({
  readyCount,
  totalSlots,
  extracting,
}: {
  readyCount: number;
  totalSlots: number;
  extracting: boolean;
}) => {
  const pct = totalSlots > 0 ? Math.round((readyCount / totalSlots) * 100) : 0;
  return (
    <div className="project-readiness-hero space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="project-readiness-label text-muted-foreground">
          Sẵn sàng tư vấn
        </span>
        <span className="project-readiness-count text-sm font-semibold tabular-nums">
          {readyCount}/{totalSlots} có thể tư vấn
        </span>
      </div>
      {/* Decorative bar — the visible "{n}/{total} có thể tư vấn" text above is the
          canonical label; the gap count is announced by the group headings below. */}
      <div
        aria-hidden="true"
        className="relative h-2.5 w-full overflow-hidden rounded-full bg-muted"
      >
        {extracting ? (
          // Indeterminate pulse — no fake sequential progress.
          <div className="absolute inset-y-0 left-0 w-1/3 animate-pulse rounded-full bg-feature-ready/60" />
        ) : (
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-feature-ready transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <i className="size-2.5 rounded-[3px] bg-feature-ready" />
          Đầy đủ
        </span>
        <span className="inline-flex items-center gap-1.5">
          <i className="size-2.5 rounded-[3px] border border-feature-gap-border border-dashed bg-feature-gap-soft" />
          Thiếu thông tin
        </span>
      </div>
    </div>
  );
};

// One of the two readiness groups.
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
    <section className="project-feature-group space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="project-feature-group-title flex items-center gap-1.5">
          {ready ? (
            <CheckCircle2 className="size-4 text-feature-ready" />
          ) : (
            <AlertCircle className="size-4 text-feature-gap" />
          )}
          {ready ? "Đã đủ thông tin" : "Cần bổ sung"}
        </h3>
        <span className="project-feature-group-count text-muted-foreground">
          {count} mục
        </span>
      </div>
      {count > 0 ? (
        <div className="project-feature-grid grid gap-2 md:grid-cols-2">
          {slots.map((f, i) => {
            const name = f?.name_vi ?? "Chưa trích xuất";
            return (
              <div
                key={f?.id ?? `slot-${i}`}
                className={cn(
                  "project-feature-chip flex items-start gap-2.5 rounded-md border bg-muted/20 px-2.5 py-2 text-xs",
                  ready
                    ? "border-feature-ready/30 bg-feature-ready-soft"
                    : "border-feature-gap-border border-dashed bg-feature-gap-soft",
                )}
              >
                <span
                  className={cn(
                    "h-[18px] w-1 shrink-0 rounded-full",
                    ready ? "bg-feature-ready/80" : "bg-feature-gap",
                  )}
                />
                <span className="project-feature-chip-copy flex min-w-0 flex-1 flex-col gap-1 text-foreground">
                  <span className="flex min-w-0 items-center gap-1">
                    <span className="truncate">{name}</span>
                  </span>
                  {!ready && f && (
                    <span className="line-clamp-2 text-[11px] leading-4 text-muted-foreground">
                      {getFillHint(f)}
                    </span>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="project-feature-empty rounded-md border border-dashed bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
          {ready ? "Chưa có mục đầy đủ." : "Không còn mục thiếu thông tin."}
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
  const [saving, setSaving] = useState(false);
  const showFillHint = feature.is_missing || feature.needs_clarification;
  const ready = isReady(feature);

  const save = async () => {
    setSaving(true);
    try {
      const updated = await updateProjectFeature(projectId, feature.id, {
        value_text: draft,
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
    setEditing(false);
  };

  return (
    <div
      className={cn(
        "min-w-0 rounded-md border p-3",
        ready && "border-feature-ready/30 bg-feature-ready-soft",
        !ready && "border-feature-gap-border bg-feature-gap-soft",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="min-w-0 text-sm font-semibold">
              {feature.name_vi}
            </span>
            {ready ? (
              <Badge
                variant="outline"
                className="border-feature-ready/25 bg-feature-ready-soft text-[10px] text-feature-ready"
              >
                Đầy đủ
              </Badge>
            ) : (
              <Badge
                variant="secondary"
                className="border border-feature-gap-border bg-feature-gap-soft text-[10px] text-feature-gap"
              >
                Thiếu thông tin
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
            </div>
          ) : (
            <>
              <p className="mt-1 text-sm leading-5">{feature.value_text}</p>
              {showFillHint && (
                <p className="mt-2 rounded-md border border-dashed bg-muted/25 px-2.5 py-2 text-xs leading-5 text-muted-foreground">
                  <span className="font-medium text-foreground">
                    Thiếu thông tin:
                  </span>{" "}
                  {getFillHint(feature)}
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
              aria-label="Hủy chỉnh sửa đặc điểm"
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
            aria-label="Chỉnh sửa đặc điểm"
            onClick={() => setEditing(true)}
          >
            <Pencil className="size-3.5" />
          </Button>
        ) : null}
      </div>
    </div>
  );
};
