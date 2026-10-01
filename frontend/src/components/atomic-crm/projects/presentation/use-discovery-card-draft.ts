import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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

const fields: DiscoveryCardField[] = [
  "summary",
  "location",
  "roles",
  "highlights",
  "aliases",
];

const readValues = (project: Project): DiscoveryCardValues => {
  const card = project.index_card ?? {};
  return {
    summary: card.summary ?? project.summary ?? "",
    location: card.location ?? "",
    roles: (card.roles ?? card.key_roles ?? []).join(", "),
    highlights: (card.highlights ?? []).join(", "),
    aliases: (project.aliases ?? []).join(", "),
  };
};

/**
 * Draft state of the discovery card — the fields the agent matches a candidate
 * against — and the single write that publishes them.
 */
export const useDiscoveryCardDraft = (project: Project): DiscoveryCardDraft => {
  const notify = useNotify();
  const refresh = useRefresh();
  const { summary, location, roles, highlights, aliases } = readValues(project);
  const incomingValues = useMemo(
    () => ({ summary, location, roles, highlights, aliases }),
    [summary, location, roles, highlights, aliases],
  );
  const [values, setValues] = useState<DiscoveryCardValues>(incomingValues);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const baselineRef = useRef({ projectId: project.id, values: incomingValues });
  const contextRef = useRef(0);

  useEffect(() => {
    const previous = baselineRef.current;
    if (previous.projectId !== project.id) {
      savingRef.current = false;
      setSaving(false);
    }
    setValues(
      (current) =>
        Object.fromEntries(
          fields.map((field) => [
            field,
            previous.projectId === project.id &&
            current[field] !== previous.values[field]
              ? current[field]
              : incomingValues[field],
          ]),
        ) as DiscoveryCardValues,
    );
    baselineRef.current = { projectId: project.id, values: incomingValues };
  }, [incomingValues, project.id]);

  useEffect(
    () => () => {
      contextRef.current += 1;
    },
    [project.id],
  );

  const setField = useCallback(
    (field: DiscoveryCardField, value: string) =>
      setValues((current) => ({ ...current, [field]: value })),
    [],
  );

  const save = useCallback(async () => {
    if (savingRef.current) return;
    const context = contextRef.current;
    savingRef.current = true;
    setSaving(true);
    try {
      await updateProjectDiscoveryCard(project.id, {
        aliases: parseCommaList(values.aliases),
        discovery_card: {
          summary: values.summary.trim(),
          location: values.location.trim(),
          roles: parseCommaList(values.roles),
          highlights: parseCommaList(values.highlights),
        },
      });
      if (context !== contextRef.current) return;
      notify("Đã cập nhật thẻ giúp ứng viên tìm thấy dự án.", {
        type: "success",
      });
      // The card is part of the project record react-admin already cached, so
      // the reviewer's record is re-read after this out-of-band write.
      refresh();
    } catch (error) {
      if (context === contextRef.current)
        notify((error as Error).message, { type: "error" });
    } finally {
      if (context === contextRef.current) {
        savingRef.current = false;
        setSaving(false);
      }
    }
  }, [notify, project.id, refresh, values]);

  return { values, saving, setField, save };
};
