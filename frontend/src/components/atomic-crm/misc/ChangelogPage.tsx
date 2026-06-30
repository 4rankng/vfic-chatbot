import { useTranslate } from "ra-core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useIsMobile } from "@/hooks/use-mobile";
import { Markdown } from "./Markdown";

const changelogContent = `## VFIC ATS Admin

### Current build

- Candidate, conversation, project, knowledge, persona, and user management are available from the admin shell.
- Dashboard focuses on chatbot delivery health, knowledge pipeline readiness, and operational attention items.
- Authentication uses VFIC email/password login with password recovery and profile management.

### QA notes

- This page now tracks VFIC-facing admin changes instead of upstream Atomic CRM template releases.
- Use the dashboard and knowledge center for live pipeline status; release details here should stay product-specific.
`;

export const ChangelogPage = () => {
  const translate = useTranslate();
  const isMobile = useIsMobile();

  if (isMobile) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-5">
        <h1 className="mb-4 text-xl font-semibold">
          {translate("crm.changelog.title")}
        </h1>
        <Markdown>{changelogContent}</Markdown>
      </div>
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
