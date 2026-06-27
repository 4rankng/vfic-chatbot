import { useEffect, useState } from "react";
import { useNotify } from "ra-core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Pencil, RefreshCw, Sparkles, X } from "lucide-react";
import {
  extractProjectFeatures,
  getProjectFeatures,
  updateProjectFeature,
} from "@/lib/vfic/knowledgeService";
import type { ProductFeature } from "../types";

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

  const load = async () => {
    setLoading(true);
    try {
      const res = await getProjectFeatures(projectId);
      setFeatures(res.data);
    } catch (err) {
      notify(`Không tải được đặc điểm: ${(err as Error).message}`, { type: "error" });
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
      notify(`Trích xuất thất bại: ${(err as Error).message}`, { type: "error" });
    } finally {
      setExtracting(false);
    }
  };

  const onUpdate = (updated: ProductFeature) => {
    setFeatures((prev) => (prev ?? []).map((f) => (f.id === updated.id ? updated : f)));
  };

  const highlightCount = (features ?? []).filter((f) => f.is_highlight).length;

  return (
    <Card className="mt-4 max-w-2xl">
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-base">
          <span>Đặc điểm sản phẩm ({features?.length ?? 0}/16)</span>
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
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 pt-2">
        <p className="text-xs text-muted-foreground">
          {highlightCount > 0
            ? `${highlightCount} điểm nổi bật của dự án.`
            : editable
              ? "Chưa có điểm nổi bật. Sửa đặc điểm và đánh dấu 'Nổi bật' để đưa vào thẻ."
              : "Chưa có điểm nổi bật cho dự án này."}
        </p>
        {loading ? (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : !features || features.length === 0 ? (
          <div className="flex flex-col items-center gap-2 rounded-md border border-dashed p-6 text-center text-muted-foreground">
            <RefreshCw className="size-6 opacity-50" />
            <p className="text-sm font-medium">Chưa có đặc điểm sản phẩm</p>
            <p className="text-xs">
              {editable
                ? 'Tải tin tuyển dụng lên rồi bấm "Trích xuất lại" để LLM trích 16 đặc điểm.'
                : "Dự án này chưa có đặc điểm sản phẩm để hiển thị."}
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {features.map((f) => (
              <FeatureCard
                key={f.id}
                projectId={projectId}
                feature={f}
                editable={editable}
                onUpdate={onUpdate}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
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
    <div className="rounded-md border p-3">
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
              <p className="mt-1 text-sm">{feature.value_text}</p>
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
            <Button size="sm" variant="ghost" onClick={cancel} disabled={saving}>
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
