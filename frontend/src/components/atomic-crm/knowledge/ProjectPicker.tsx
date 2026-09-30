import { useMemo, useState } from "react";
import {
  useDataProvider,
  useGetList,
  useGetOne,
  useNotify,
  useRefresh,
} from "ra-core";
import { Select as UntitledSelect } from "@/components/base/select/select";
import type { SelectItemType } from "@/components/base/select/select-shared";
import type { KnowledgeBase, Project } from "../types";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import { normalizeSearch, slugifyProject } from "./projectPickerUtils";

/** Sentinel id for the "create project" row; project ids cannot collide. */
const CREATE_KEY = "__create__";
/** Sentinel id for the empty-result row; project ids cannot collide. */
const EMPTY_KEY = "__empty__";

export const ProjectPicker = ({
  value,
  onChange,
  id,
}: {
  value: string;
  onChange: (value: string) => void;
  id?: string;
}) => {
  const notify = useNotify();
  const refresh = useRefresh();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [localProjects, setLocalProjects] = useState<Project[]>([]);
  const trimmedSearch = search.trim();
  const { data: selectedProjectRecord } = useGetOne<Project>(
    "projects",
    { id: value! },
    { enabled: !!value },
  );
  const { data: searchedProjects } = useGetList<Project>("projects", {
    pagination: { page: 1, perPage: 25 },
    sort: { field: "name", order: "ASC" },
    filter: trimmedSearch ? { q: trimmedSearch } : {},
  });
  const { data: knowledgeBases = [] } = useGetList<KnowledgeBase>(
    "knowledge_bases",
    {
      pagination: { page: 1, perPage: 100 },
      sort: { field: "name", order: "ASC" },
      filter: {},
    },
  );
  const ragKnowledgeBases = knowledgeBases.filter(
    (knowledgeBase) => knowledgeBase.mode === "RAG",
  );
  const creationKnowledgeBaseId =
    ragKnowledgeBases.length === 1 ? ragKnowledgeBases[0].id : null;

  const availableProjects = useMemo(() => {
    const map = new Map<string, Project>();
    for (const project of searchedProjects ?? []) {
      map.set(String(project.id), project);
    }
    if (!trimmedSearch && selectedProjectRecord) {
      map.set(String(selectedProjectRecord.id), selectedProjectRecord);
    }
    for (const project of localProjects) map.set(String(project.id), project);
    return Array.from(map.values()).sort((a, b) =>
      a.name.localeCompare(b.name, "vi"),
    );
  }, [localProjects, searchedProjects, selectedProjectRecord, trimmedSearch]);

  const normalizedSearch = normalizeSearch(trimmedSearch);
  const exactMatch = availableProjects.some(
    (project) => normalizeSearch(project.name) === normalizedSearch,
  );
  const canCreate = trimmedSearch.length > 0 && !exactMatch;
  const createHelpText = !trimmedSearch
    ? "Nhập tên dự án để tạo mới."
    : exactMatch
      ? "Dự án này đã tồn tại."
      : `Tạo dự án "${trimmedSearch}"`;

  const selectProject = (projectId: string) => {
    onChange(projectId);
    setSearch("");
  };

  const createProject = async () => {
    if (!canCreate || creating) return;
    setCreating(true);
    try {
      if (!creationKnowledgeBaseId) {
        notify(
          ragKnowledgeBases.length === 0
            ? "Tạo Knowledge Base RAG trước khi tạo dự án."
            : "Tạo dự án trong trang Dự án để chọn Knowledge Base RAG.",
          { type: "warning" },
        );
        return;
      }
      const response = await dataProvider.create("projects", {
        data: {
          name: trimmedSearch,
          slug: slugifyProject(trimmedSearch),
          is_active: true,
          knowledge_base_id: creationKnowledgeBaseId,
        },
      });
      const project = response.data as Project;
      setLocalProjects((current) => [...current, project]);
      onChange(String(project.id));
      notify("Đã tạo dự án.", { type: "success" });
      setSearch("");
      refresh();
    } catch (err) {
      notify(`Tạo dự án thất bại: ${(err as Error).message}`, {
        type: "error",
      });
    } finally {
      setCreating(false);
    }
  };

  const items: SelectItemType[] = availableProjects.map((project) => ({
    id: String(project.id),
    label: project.name,
    supportingText: project.slug,
  }));
  if (canCreate) {
    items.push({ id: CREATE_KEY, label: createHelpText, isDisabled: creating });
  } else if (items.length === 0) {
    items.push({
      id: EMPTY_KEY,
      label: "Không tìm thấy dự án.",
      isDisabled: true,
    });
  }

  return (
    <UntitledSelect.ComboBox
      id={id}
      className="uu-scope"
      aria-label="Dự án"
      placeholder="Chọn dự án"
      items={items}
      selectedKey={value || null}
      inputValue={search}
      onInputChange={setSearch}
      onSelectionChange={(key) => {
        if (key === CREATE_KEY) {
          void createProject();
          return;
        }
        if (key === null || key === EMPTY_KEY) return;
        selectProject(String(key));
      }}
      validationBehavior="aria"
    >
      {(item: SelectItemType) => (
        <UntitledSelect.Item
          id={item.id}
          label={item.label}
          supportingText={item.supportingText}
          isDisabled={item.isDisabled}
        />
      )}
    </UntitledSelect.ComboBox>
  );
};
