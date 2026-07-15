import { useState } from "react";
import { Braces, Eye, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  assignIngestionTemplate,
  createIngestionTemplate,
  getIngestionTemplateAssignment,
  previewIngestionTemplate,
  previewNewIngestionTemplate,
  publishIngestionTemplate,
  type IngestionPreview,
} from "@/lib/vfic/knowledgeService";

const cleanKey = (value: string) =>
  value
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");

export const IngestionTemplateBuilder = () => {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [vertical, setVertical] = useState("shopping");
  const [recordName, setRecordName] = useState("product");
  const [fields, setFields] = useState("sku, name, description");
  const [sample, setSample] = useState("SKU: SP-001\nTên: Áo khoác\nMô tả: Chống nước");
  const [projectId, setProjectId] = useState("");
  const [preview, setPreview] = useState<IngestionPreview | null>(null);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const definition = () => {
    const recordKey = cleanKey(recordName);
    const fieldKeys = fields
      .split(",")
      .map(cleanKey)
      .filter(Boolean);
    return {
      schema_version: "1",
      record_types: [
        {
          key: recordKey,
          display_name: recordName.trim(),
          natural_key_fields: [fieldKeys[0] ?? "id"],
          fields: fieldKeys.map((key, index) => ({
            key,
            type: "string",
            aliases: [key, key.replace(/_/g, " ")],
            required: index === 0,
            source_mode: "sourced_fact",
          })),
        },
      ],
    };
  };

  const applyStarter = (starter: "shopping" | "logistics" | "recruitment") => {
    if (starter === "shopping") {
      setName("Danh mục sản phẩm");
      setVertical("shopping");
      setRecordName("product");
      setFields("sku, name, material, warranty");
      setSample("SKU: SP-001\nTên sản phẩm: Áo khoác\nChất liệu: Polyester\nBảo hành: 12 tháng");
      return;
    }
    if (starter === "logistics") {
      setName("Dịch vụ vận tải");
      setVertical("logistics");
      setRecordName("transport_service");
      setFields("service_code, service_name, vehicle_capability");
      setSample("Mã dịch vụ: TRUCK-01\nTên dịch vụ: Hàng nguyên chuyến\nNăng lực xe: 15 tấn");
      return;
    }
    setName("Tuyển dụng công nhân");
    setVertical("recruitment");
    setRecordName("job_posting");
    setFields("job_reference, title, employer, worksite");
    setSample("Mã việc làm: JOB-001\nVị trí: Công nhân hàn\nCông ty: VFIC\nNhà máy: Đồng Nai");
  };

  const runPreview = async () => {
    setBusy(true);
    setError(null);
    try {
      setPreview(await previewNewIngestionTemplate(definition(), sample));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không thể kiểm tra mẫu.");
    } finally {
      setBusy(false);
    }
  };

  const publish = async () => {
    setBusy(true);
    setError(null);
    try {
      let versionId = draftId;
      if (!versionId) {
        const created = await createIngestionTemplate({
          template_key: `${cleanKey(name) || cleanKey(recordName)}_${Date.now()}`,
          name: name.trim() || recordName.trim(),
          vertical,
          definition: definition(),
        });
        versionId = created.id;
        setDraftId(versionId);
      }
      // Publishing requires a successful preview recorded on this exact draft.
      await previewIngestionTemplate(versionId, sample);
      const published = await publishIngestionTemplate(versionId);
      if (projectId.trim()) {
        const current = await getIngestionTemplateAssignment(projectId.trim());
        await assignIngestionTemplate(
          projectId.trim(),
          published.id,
          (current?.revision ?? 0) + 1,
        );
      }
      setOpen(false);
      setPreview(null);
      setDraftId(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không thể xuất bản mẫu.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline" className="h-10 rounded-[9px]">
          <Braces className="size-4" />
          Mẫu ingest
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Tạo mẫu ingest</DialogTitle>
          <DialogDescription>
            Khai báo các trường dữ liệu có cấu trúc. Mẫu chỉ đọc dữ liệu có bằng chứng từ tài liệu; không thể thêm lệnh, công cụ hoặc prompt.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap gap-2 border-b pb-4">
          <span className="mr-1 self-center text-xs font-medium uppercase tracking-wide text-muted-foreground">Bắt đầu từ</span>
          <Button type="button" size="sm" variant="outline" onClick={() => applyStarter("recruitment")}>Tuyển dụng</Button>
          <Button type="button" size="sm" variant="outline" onClick={() => applyStarter("shopping")}>Sản phẩm</Button>
          <Button type="button" size="sm" variant="outline" onClick={() => applyStarter("logistics")}>Logistics</Button>
        </div>
        <div className="grid gap-4 py-2 sm:grid-cols-2">
          <div className="grid gap-2"><Label htmlFor="template-name">Tên mẫu</Label><Input id="template-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Danh mục sản phẩm" /></div>
          <div className="grid gap-2"><Label htmlFor="template-vertical">Lĩnh vực</Label><Input id="template-vertical" value={vertical} onChange={(event) => setVertical(event.target.value)} placeholder="shopping hoặc logistics" /></div>
          <div className="grid gap-2"><Label htmlFor="record-name">Loại bản ghi</Label><Input id="record-name" value={recordName} onChange={(event) => setRecordName(event.target.value)} placeholder="product" /></div>
          <div className="grid gap-2"><Label htmlFor="record-fields">Các trường (cách nhau dấu phẩy)</Label><Input id="record-fields" value={fields} onChange={(event) => setFields(event.target.value)} placeholder="sku, name, warranty" /></div>
          <div className="grid gap-2 sm:col-span-2"><Label htmlFor="template-project">Dự án áp dụng (không bắt buộc)</Label><Input id="template-project" value={projectId} onChange={(event) => setProjectId(event.target.value)} placeholder="ID dự án — mẫu sẽ áp dụng cho các KB mới" /></div>
          <div className="grid gap-2 sm:col-span-2"><Label htmlFor="template-sample">Dữ liệu thử</Label><Textarea id="template-sample" value={sample} onChange={(event) => setSample(event.target.value)} rows={7} /></div>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        {preview && <div className="rounded-md border p-3 text-sm"><strong>Xem trước: {preview.records.length} bản ghi</strong><pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap">{JSON.stringify(preview, null, 2)}</pre></div>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" disabled={busy} onClick={() => void runPreview()}><Eye className="size-4" /> Xem trước</Button>
          <Button type="button" disabled={busy || !preview} onClick={() => void publish()}><Send className="size-4" /> Xuất bản</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};
