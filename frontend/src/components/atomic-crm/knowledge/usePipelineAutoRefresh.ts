import { useEffect } from "react";
import { useRefresh } from "ra-core";

import type { KnowledgeSource } from "../types";
import { isPipelineActive } from "./knowledgePipelineUtils";

const REFRESH_INTERVAL_MS = 5000;

/**
 * Auto-refresh the knowledge-source list every 5s while a source is actively
 * moving through the pipeline, and never while the tab is hidden: the interval
 * is disarmed while `document.visibilityState` is hidden and re-arms on
 * visibilitychange, matching the ExternalSourceList convention
 * (refetchIntervalInBackground: false) so a background tab does not keep
 * hitting the backend for the whole pipeline duration.
 */
export const usePipelineAutoRefresh = (sources: KnowledgeSource[]) => {
  const refresh = useRefresh();

  useEffect(() => {
    if (!sources.some(isPipelineActive)) return;

    let timer: number | null = null;
    const stop = () => {
      if (timer !== null) {
        window.clearInterval(timer);
        timer = null;
      }
    };
    const start = () => {
      if (timer === null) {
        timer = window.setInterval(() => refresh(), REFRESH_INTERVAL_MS);
      }
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") stop();
      else start();
    };

    if (document.visibilityState !== "hidden") start();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      stop();
    };
  }, [refresh, sources]);
};
