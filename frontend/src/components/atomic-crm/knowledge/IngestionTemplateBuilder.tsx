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
  createIngestionTemplate,
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
  const [preview, setPreview] = useState<IngestionPreview | null>(null);
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
      const created = await createIngestionTemplate({
        template_key: `${cleanKey(name) || cleanKey(recordName)}_${Date.now()}`,
        name: name.trim() || recordName.trim(),
        vertical,
        definition: definition(),
      });
      await publishIngestionTemplate(created.id);
      setOpen(false);
      setPreview(null);
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
        <div className="grid gap-4 py-2 sm:grid-cols-2">
          <div className="grid gap-2"><Label htmlFor="template-name">Tên mẫu</Label><Input id="template-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Danh mục sản phẩm" /></div>
          <div className="grid gap-2"><Label htmlFor="template-vertical">Lĩnh vực</Label><Input id="template-vertical" value={vertical} onChange={(event) => setVertical(event.target.value)} placeholder="shopping hoặc logistics" /></div>
          <div className="grid gap-2"><Label htmlFor="record-name">Loại bản ghi</Label><Input id="record-name" value={recordName} onChange={(event) => setRecordName(event.target.value)} placeholder="product" /></div>
          <div className="grid gap-2"><Label htmlFor="record-fields">Các trường (cách nhau dấu phẩy)</Label><Input id="record-fields" value={fields} onChange={(event) => setFields(event.target.value)} placeholder="sku, name, warranty" /></div>
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
