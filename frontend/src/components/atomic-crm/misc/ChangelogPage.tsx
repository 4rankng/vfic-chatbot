import { useTranslate } from "ra-core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useIsMobile } from "@/hooks/use-mobile";
import { Markdown } from "./Markdown";
import changelogContent from "../../../../CHANGELOG.md?raw";

export const ChangelogPage = () => {
  const translate = useTranslate();
  const isMobile = useIsMobile();

  if (isMobile) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-5">
        <h1 className="mb-4 text-xl font-semibold">
          {translate("crm.changelog.title")}
        </h1>
        <Markdown>{changelogContent}</Markdown>
      </main>
    );
  }

  return (
    <div className="max-w-3xl mx-auto my-8">
      <Card>
        <CardHeader>
          <CardTitle>{translate("crm.changelog.title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <Markdown>{changelogContent}</Markdown>
        </CardContent>
      </Card>
    </div>
  );
};

ChangelogPage.path = "/changelog";
