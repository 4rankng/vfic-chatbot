import { useMemo, useState } from "react";
import { useGetList, useListContext } from "ra-core";

import type { KnowledgeSource, Project } from "../types";
import {
  needsReview,
  sourceSearchText,
  sourceStage,
} from "./knowledgePipelineUtils";
import { normalizeVietnameseSearchText } from "@/lib/vietnameseSearch";

// Sentinel option values for the "all" project / stage filter selects.
export const ALL_PROJECTS = "__all__";
export const ALL_STAGES = "__all__";

/**
 * Owns the knowledge-source inbox's filtering concern: reads the RA list
 * context + the project list, holds the query/project/stage/review filters,
 * and derives projectById / stages / filteredSources. Extracted from
 * KnowledgeSourceListContent so the orchestrator is left with selection,
 * auto-refresh, and rendering only.
 */
export const useKnowledgeSourceFilters = () => {
  const { data, isPending } = useListContext<KnowledgeSource>();
  const { data: projects } = useGetList<Project>("projects", {
    pagination: { page: 1, perPage: 100 },
    sort: { field: "name", order: "ASC" },
  });

  const [query, setQuery] = useState("");
  const [projectFilter, setProjectFilter] = useState(ALL_PROJECTS);
  const [stageFilter, setStageFilter] = useState(ALL_STAGES);
  const [reviewOnly, setReviewOnly] = useState(false);

  const projectById = useMemo(() => {
    const map = new Map<string, Project>();
    for (const project of projects ?? []) map.set(String(project.id), project);
    return map;
  }, [projects]);

  const sources = useMemo(() => data ?? [], [data]);
  const stages = useMemo(
    () => Array.from(new Set(sources.map(sourceStage))).sort(),
    [sources],
  );

  const filteredSources = useMemo(() => {
    const needle = normalizeVietnameseSearchText(query);
    return sources.filter((source) => {
      if (
        projectFilter !== ALL_PROJECTS &&
        String(source.project_id ?? "") !== projectFilter
      )
        return false;
      if (stageFilter !== ALL_STAGES && stageFilter !== sourceStage(source))
        return false;
      if (reviewOnly && !needsReview(source)) return false;
      if (!needle) return true;
      return sourceSearchText(
        source,
        source.project_id
          ? projectById.get(String(source.project_id))?.name
          : "",
      ).includes(needle);
    });
  }, [projectById, projectFilter, query, reviewOnly, sources, stageFilter]);

  const selectProject = (projectId: string) => {
    setProjectFilter(projectId);
    setStageFilter(ALL_STAGES);
    setReviewOnly(false);
  };

  return {
    isPending,
    projects,
    projectById,
    sources,
    stages,
    filteredSources,
    query,
    setQuery,
    projectFilter,
    stageFilter,
    reviewOnly,
    setProjectFilter,
    setStageFilter,
    setReviewOnly,
    selectProject,
  };
};
