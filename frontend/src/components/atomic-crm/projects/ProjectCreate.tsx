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
import { BooleanInput } from "@/components/admin/boolean-input";
import { TopToolbar } from "../layout/TopToolbar";
import { Button } from "@/components/ui/button";
import type { CrmDataProvider } from "../providers/rest/dataProvider";

export const ProjectCreate = () => {
  const notify = useNotify();
  const redirect = useRedirect();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (data: Record<string, unknown>) => {
    setSubmitting(true);
    try {
      await dataProvider.create("projects", { data });
      notify("Đã tạo dự án.", { type: "success" });
      redirect("/projects");
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <CreateBase resource="projects">
      <TopToolbar>
        <h2 className="mr-auto text-xl font-semibold">Tạo dự án</h2>
      </TopToolbar>
      <Card className="mt-4 max-w-2xl">
        <CardContent className="pt-6">
          <Form onSubmit={onSubmit}>
            <div className="flex flex-col gap-4">
              <TextInput source="name" label="Tên dự án" isRequired />
              <TextInput
                source="slug"
                label="Slug (không dấu, không khoảng cách)"
                isRequired
              />
              <BooleanInput
                source="is_active"
                label="Đang hoạt động"
                defaultValue={true}
              />
              <Button type="submit" disabled={submitting}>
                Tạo dự án
              </Button>
            </div>
          </Form>
        </CardContent>
      </Card>
    </CreateBase>
  );
};
