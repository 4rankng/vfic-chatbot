import { useEffect, useState } from "react";

import { listExternalSources } from "../project-knowledge-service";

export type FaqAutoSyncNoticeOptions = Readonly<{
  /** Only source managers may read the external-source rows. */
  enabled: boolean;
  /** Changes whenever the project's external sources change. */
  refreshSignal: number;
}>;

/** Whether the FAQ category is fed by a scheduled Google Sheet sync. */
export const useFaqAutoSyncNotice = (
  projectId: string,
  { enabled, refreshSignal }: FaqAutoSyncNoticeOptions,
): boolean => {
  const [autoSyncOn, setAutoSyncOn] = useState(false);

  useEffect(() => {
    if (!enabled) {
      setAutoSyncOn(false);
      return;
    }
    let active = true;
    listExternalSources(projectId)
      .then((rows) => {
        if (!active) return;
        setAutoSyncOn(
          rows.some(
            (row) => row.category_key === "faq" && row.auto_sync_enabled,
          ),
        );
      })
      .catch(() => {
        /* external-source list is optional; never block the panel */
      });
    return () => {
      active = false;
    };
  }, [enabled, projectId, refreshSignal]);

  return autoSyncOn;
};
