import { useCallback, useMemo } from "react";
import { useGetList, useListContext } from "ra-core";

import type { KnowledgeSource, Project } from "../types";

// Sentinel option values for the "all" project / stage filter selects.
export const ALL_PROJECTS = "__all__";
export const ALL_STAGES = "__all__";

/**
 * Owns the knowledge-source inbox's backend filter controls. The document rows,
 * filtered total, and pagination all come from the ListBase/dataProvider/API
 * contract; this hook does not filter or count document rows in memory.
 */
export const useKnowledgeSourceFilters = () => {
  const {
    data,
    isPending,
    filterValues,
    setFilters,
    setPage,
    total,
  } = useListContext<KnowledgeSource>();
  const { data: projects } = useGetList<Project>("projects", {
    pagination: { page: 1, perPage: 100 },
    sort: { field: "name", order: "ASC" },
  });

  const filters = filterValues ?? {};
  const query = typeof filters.q === "string" ? filters.q : "";
  const projectFilter =
    typeof filters.project_id === "string" ? filters.project_id : ALL_PROJECTS;

  const projectById = useMemo(() => {
    const map = new Map<string, Project>();
    for (const project of projects ?? []) map.set(String(project.id), project);
    return map;
  }, [projects]);

  const sources = useMemo(() => data ?? [], [data]);

  const updateFilters = useCallback(
    (next: Record<string, string | boolean | undefined>) => {
      const merged = { ...filters, ...next };
      for (const [key, value] of Object.entries(merged)) {
        if (value === undefined || value === "" || value === ALL_PROJECTS) {
          delete merged[key];
        }
      }
      setPage(1);
      setFilters(merged);
    },
    [filters, setFilters, setPage],
  );

  const setQuery = useCallback(
    (value: string) => updateFilters({ q: value }),
    [updateFilters],
  );

  const selectProject = (projectId: string) => {
    updateFilters({ project_id: projectId });
  };

  return {
    isPending,
    projects,
    projectById,
    sources,
    pageSources: sources,
    total: total ?? 0,
    query,
    setQuery,
    projectFilter,
    selectProject,
  };
};
