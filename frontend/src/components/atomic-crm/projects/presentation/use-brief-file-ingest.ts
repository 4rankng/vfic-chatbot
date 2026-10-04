import { useRef, useState } from "react";

import type { ProjectKnowledgeCategory } from "../domain/project-knowledge-policy";
import {
  PROJECT_KNOWLEDGE_CATEGORIES,
  PROJECT_KNOWLEDGE_CATEGORY_LABELS,
} from "../domain/project-knowledge-policy";
import {
  assertProjectTextFile,
  type KnowledgeCategoryKey,
} from "../project-knowledge-service";
import { useProjectIngest } from "./use-project-ingest";

type Options = {
  /** Blocks picking a new file while a migration owns the chain. */
  disabled: boolean;
  /** Refreshes the catalog after review lands. */
  onIngested?: (
    categories: readonly ProjectKnowledgeCategory[],
  ) => Promise<void>;
  /** Resolves only after the explicit category-authority cutover succeeds. */
  onCutover?: (
    categories: readonly ProjectKnowledgeCategory[],
  ) => Promise<void>;
};

/**
 * The text-brief file chain shared by the workspace command bar and the
 * migration section: validate the pick, run the ingest, and report which
 * categories still need a human. A browser preview never determines the
 * category set or completion.
 */
export const useBriefFileIngest = (
  projectId: string,
  { disabled, onIngested, onCutover }: Options,
) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const { state, ingest } = useProjectIngest();
  /** Vietnamese labels of the categories this brief cannot seed. */
  const [needsHuman, setNeedsHuman] = useState<string[] | null>(null);
  const [error, setError] = useState("");

  const read = async (file?: File) => {
    if (!file) return;
    setError("");
    setNeedsHuman(null);
    try {
      assertProjectTextFile(file);
      const result = await ingest(projectId, [], file);
      if (!result.ok) return;
      setNeedsHuman(
        PROJECT_KNOWLEDGE_CATEGORIES.filter(
          (key) => !result.activated.includes(key),
        ).map((key) => PROJECT_KNOWLEDGE_CATEGORY_LABELS[key]),
      );
      // Review can finish as a shadow batch while the single-page source is
      // still live. Complete the explicit migration before publishing claims.
      if (result.requiresCutover && !onCutover) {
        // Another admin may have rolled back while this panel was open.
        // A catalog reload cannot make the prepared source authoritative.
        await onIngested?.(result.activated);
        return;
      }
      // The migration's explicit intent also applies to older receipts that
      // omit requires_cutover. Never infer successful cutover from a reload.
      await onCutover?.(result.activated);
      await onIngested?.(result.activated);
    } catch (readError) {
      setError((readError as Error).message);
    } finally {
      // Allow re-picking the same file after an edit.
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return {
    inputRef,
    state,
    needsHuman,
    error,
    ingesting: state.phase === "running",
    read: (file?: File) => {
      if (disabled) return Promise.resolve();
      return read(file);
    },
  };
};

export type BriefFileIngest = ReturnType<typeof useBriefFileIngest>;

/** Re-exported for the strip's hidden input markup. */
export type { KnowledgeCategoryKey };
