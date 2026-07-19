import { useState } from "react";
import {
  CreateBase,
  Form,
  useDataProvider,
  useNotify,
  useRedirect,
} from "ra-core";
import { Card, CardContent } from "@/components/ui/card";
import { TextInput } from "@/components/admin/text-input";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { X } from "lucide-react";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import { ProjectWorkspaceShell } from "./ProjectWorkspaceShell";

export const ProjectCreate = () => {
  const notify = useNotify();
  const redirect = useRedirect();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const [submitting, setSubmitting] = useState(false);
  const [mode, setMode] = useState<"" | "RAG" | "DIRECT_CONTEXT">("");
  const [aliases, setAliases] = useState("");
  const [summary, setSummary] = useState("");
  const [location, setLocation] = useState("");
  const [roles, setRoles] = useState("");
  const [highlights, setHighlights] = useState("");

  const onSubmit = async (data: Record<string, unknown>) => {
    setSubmitting(true);
    try {
      if (!mode) {
        notify("Chọn một cách lưu kiến thức để tiếp tục.", { type: "warning" });
        setSubmitting(false);
        return;
      }
      const discoveryCard =
        mode === "DIRECT_CONTEXT"
          ? {
              summary: summary.trim(),
              location: location.trim(),
              roles: splitList(roles),
              eligibility: [],
              highlights: splitList(highlights),
            }
          : undefined;
      if (mode === "DIRECT_CONTEXT" && (!summary.trim() || !location.trim())) {
        notify(
          "Vui lòng nhập tóm tắt và địa điểm để Agent có thể gợi ý dự án.",
          {
            type: "warning",
          },
        );
        setSubmitting(false);
        return;
      }
      const created = await dataProvider.create("projects", {
        data: {
          ...data,
          knowledge_mode: mode,
          aliases: splitList(aliases),
          discovery_card: discoveryCard,
          is_active: false,
        },
      });
      notify("Đã tạo dự án.", { type: "success" });
      redirect("edit", "projects", created.data.id);
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <CreateBase resource="projects">
      <ProjectWorkspaceShell>
        <div className="project-workspace-content">
          <div className="project-create-shell mx-auto w-full max-w-4xl">
            <header className="project-editor-header flex flex-wrap items-start gap-4 rounded-lg border p-4">
              <div className="mr-auto min-w-0">
                <p className="text-helper font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  Dự án
                </p>
                <h1 className="mt-1 text-content-title font-semibold">
                  Tạo dự án
                </h1>
                <p className="mt-1 text-body text-muted-foreground">
                  Tạo không gian huấn luyện riêng cho một dự án tuyển dụng.
                </p>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => redirect("/projects")}
                aria-label="Đóng và quay lại danh sách dự án"
              >
                <X className="size-4" aria-hidden="true" />
                Đóng
              </Button>
            </header>
            <Card className="mt-4 w-full">
              <CardContent className="pt-6">
                <Form onSubmit={onSubmit}>
                  <div className="flex flex-col gap-4">
                    <TextInput source="name" label="Tên dự án" isRequired />
                    <TextInput
                      source="slug"
                      label="Slug (không dấu, không khoảng cách)"
                      isRequired
                    />
                    <fieldset className="grid gap-2">
                      <legend className="font-medium">
                        Cách lưu kiến thức
                      </legend>
                      <label className="flex cursor-pointer gap-3 rounded-lg border p-4">
                        <input
                          className="tt-radio tt-radio-primary tt-radio-sm mt-1"
                          type="radio"
                          name="knowledge-mode"
                          value="DIRECT_CONTEXT"
                          checked={mode === "DIRECT_CONTEXT"}
                          onChange={() => setMode("DIRECT_CONTEXT")}
                        />
                        <span>
                          <span className="block font-semibold">Một trang</span>
                          <span className="text-helper text-muted-foreground">
                            Quản lý toàn bộ thông tin trong một nội dung duy
                            nhất. Mỗi lần cập nhật sẽ thay thế toàn bộ nội dung
                            cũ.
                          </span>
                        </span>
                      </label>
                      <label className="flex cursor-pointer gap-3 rounded-lg border p-4">
                        <input
                          className="tt-radio tt-radio-primary tt-radio-sm mt-1"
                          type="radio"
                          name="knowledge-mode"
                          value="RAG"
                          checked={mode === "RAG"}
                          onChange={() => setMode("RAG")}
                        />
                        <span>
                          <span className="block font-semibold">
                            Theo danh mục
                          </span>
                          <span className="text-helper text-muted-foreground">
                            Chia kiến thức thành 12 nhóm để cập nhật từng phần
                            độc lập.
                          </span>
                        </span>
                      </label>
                      <p className="text-helper text-muted-foreground">
                        Không thể đổi cách lưu sau khi dự án đã có dữ liệu.
                      </p>
                    </fieldset>
                    <Input
                      value={aliases}
                      onChange={(event) => setAliases(event.target.value)}
                      placeholder="Tên gọi khác, ví dụ: LG, LGD"
                      aria-label="Tên gọi khác của dự án"
                    />
                    {mode === "DIRECT_CONTEXT" && (
                      <div className="grid gap-3 rounded-lg border p-4">
                        <p className="font-medium">
                          Thông tin giúp ứng viên tìm thấy dự án
                        </p>
                        <Input
                          value={summary}
                          onChange={(event) => setSummary(event.target.value)}
                          placeholder="Tóm tắt dự án"
                        />
                        <Input
                          value={location}
                          onChange={(event) => setLocation(event.target.value)}
                          placeholder="Địa điểm"
                        />
                        <Input
                          value={roles}
                          onChange={(event) => setRoles(event.target.value)}
                          placeholder="Vị trí, cách nhau bằng dấu phẩy"
                        />
                        <Input
                          value={highlights}
                          onChange={(event) =>
                            setHighlights(event.target.value)
                          }
                          placeholder="Điểm nổi bật, cách nhau bằng dấu phẩy"
                        />
                      </div>
                    )}
                    <p className="text-helper text-muted-foreground">
                      Dự án sẽ ở trạng thái tắt cho đến khi có kiến thức hợp lệ.
                    </p>
                    <Button type="submit" disabled={submitting}>
                      Tạo dự án
                    </Button>
                  </div>
                </Form>
              </CardContent>
            </Card>
          </div>
        </div>
      </ProjectWorkspaceShell>
    </CreateBase>
  );
};

const splitList = (value: string) =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
