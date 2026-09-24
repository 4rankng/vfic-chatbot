import { useCallback, useState } from "react";
import { useNotify, useRefresh } from "ra-core";

import type { Project } from "../../types";
import { parseCommaList } from "../domain/project-knowledge-policy";
import { updateProjectDiscoveryCard } from "../project-knowledge-service";

export type DiscoveryCardField =
  | "summary"
  | "location"
  | "roles"
  | "highlights"
  | "aliases";

export type DiscoveryCardValues = Readonly<Record<DiscoveryCardField, string>>;

export type DiscoveryCardDraft = Readonly<{
  values: DiscoveryCardValues;
  saving: boolean;
  setField: (field: DiscoveryCardField, value: string) => void;
  save: () => Promise<void>;
}>;

/**
 * Draft state of the discovery card — the fields the agent matches a candidate
 * against — and the single write that publishes them.
 */
export const useDiscoveryCardDraft = (project: Project): DiscoveryCardDraft => {
  const notify = useNotify();
  const refresh = useRefresh();
  const card = project.index_card ?? {};
  const [values, setValues] = useState<DiscoveryCardValues>(() => ({
    summary: card.summary ?? project.summary ?? "",
    location: card.location ?? "",
    roles: (card.roles ?? card.key_roles ?? []).join(", "),
    highlights: (card.highlights ?? []).join(", "),
    aliases: (project.aliases ?? []).join(", "),
  }));
  const [saving, setSaving] = useState(false);

  const setField = useCallback(
    (field: DiscoveryCardField, value: string) =>
      setValues((current) => ({ ...current, [field]: value })),
    [],
  );

  const save = useCallback(async () => {
    setSaving(true);
    try {
      await updateProjectDiscoveryCard(project.id, {
        aliases: parseCommaList(values.aliases),
        discovery_card: {
          summary: values.summary.trim(),
          location: values.location.trim(),
          roles: parseCommaList(values.roles),
          eligibility: [],
          highlights: parseCommaList(values.highlights),
        },
      });
      notify("Đã cập nhật thẻ giúp ứng viên tìm thấy dự án.", {
        type: "success",
      });
      // The card is part of the project record react-admin already cached, so
      // the reviewer's record is re-read after this out-of-band write.
      refresh();
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setSaving(false);
    }
  }, [notify, project.id, refresh, values]);

  return { values, saving, setField, save };
};
