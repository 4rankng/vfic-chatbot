import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { Project } from "../../types";
import { useDiscoveryCardDraft } from "./use-discovery-card-draft";

/** Editor for the discovery card the agent matches candidates against. */
export const DiscoveryCardEditor = ({ project }: { project: Project }) => {
  const { saving, save, setField, values } = useDiscoveryCardDraft(project);

  return (
    <Card className="project-discovery-card">
      <CardHeader className="project-discovery-header">
        <CardTitle className="text-section-title">
          Thông tin dùng khi gợi ý dự án
        </CardTitle>
      </CardHeader>
      <CardContent className="project-discovery-content grid gap-3 sm:grid-cols-2">
        <Input
          value={values.summary}
          onChange={(event) => setField("summary", event.target.value)}
          placeholder="Tóm tắt"
          aria-label="Tóm tắt dự án"
        />
        <Input
          value={values.location}
          onChange={(event) => setField("location", event.target.value)}
          placeholder="Địa điểm"
          aria-label="Địa điểm dự án"
        />
        <Input
          value={values.roles}
          onChange={(event) => setField("roles", event.target.value)}
          placeholder="Vị trí, cách nhau bằng dấu phẩy"
          aria-label="Vị trí tuyển dụng"
        />
        <Input
          value={values.highlights}
          onChange={(event) => setField("highlights", event.target.value)}
          placeholder="Điểm nổi bật, cách nhau bằng dấu phẩy"
          aria-label="Điểm nổi bật"
        />
        <Input
          value={values.aliases}
          onChange={(event) => setField("aliases", event.target.value)}
          placeholder="Tên gọi khác: LG, LGD..."
          aria-label="Tên gọi khác"
        />
        <div>
          <Button
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
