import { useId } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Project } from "../../types";
import { useDiscoveryCardDraft } from "./use-discovery-card-draft";

/** Editor for the discovery card the agent matches candidates against. */
export const DiscoveryCardEditor = ({ project }: { project: Project }) => {
  const { saving, save, setField, values } = useDiscoveryCardDraft(project);
  const formId = useId();
  const fields = [
    {
      key: "summary",
      label: "Tóm tắt dự án",
      placeholder: "Điểm chính giúp ứng viên hiểu dự án",
    },
    {
      key: "location",
      label: "Địa điểm dự án",
      placeholder: "Ví dụ: Hải Phòng",
    },
    {
      key: "roles",
      label: "Vị trí tuyển dụng",
      placeholder: "Các vị trí, cách nhau bằng dấu phẩy",
    },
    {
      key: "highlights",
      label: "Điểm nổi bật",
      placeholder: "Các điểm nổi bật, cách nhau bằng dấu phẩy",
    },
    { key: "aliases", label: "Tên gọi khác", placeholder: "Ví dụ: LG, LGD" },
  ] as const;

  return (
    <Card className="project-discovery-card">
      <CardHeader className="project-discovery-header">
        <CardTitle className="text-section-title">
          Thông tin dùng khi gợi ý dự án
        </CardTitle>
      </CardHeader>
      <CardContent
        className="project-discovery-content grid gap-3 sm:grid-cols-2"
        aria-busy={saving}
      >
        {fields.map((field) => (
          <div key={field.key} className="grid min-w-0 gap-1.5">
            <Label htmlFor={`${formId}-${field.key}`}>{field.label}</Label>
            <Input
              id={`${formId}-${field.key}`}
              value={values[field.key]}
              onChange={(event) => setField(field.key, event.target.value)}
              placeholder={field.placeholder}
              disabled={saving}
            />
          </div>
        ))}
        <div>
          <Button
            type="button"
            className="project-discovery-save"
            onClick={() => void save()}
            disabled={saving}
          >
            {saving ? (
              <span
                className="tt-loading tt-loading-spinner tt-loading-sm"
                aria-hidden="true"
              />
            ) : null}
            Lưu thông tin gợi ý
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};
