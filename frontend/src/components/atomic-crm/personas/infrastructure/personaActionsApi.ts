import { apiJson } from "../../providers/rest/api";
import type {
  AdapterPersonaAssignment,
} from "../../types";
import type {
  ImportedPersona,
  PersonaActionsPort,
} from "../application/ports";

const BASE = "/api/v1/knowledge";

export const personaActionsApi: PersonaActionsPort = {
  async activatePersona(id) {
    await apiJson(`${BASE}/personas/${encodeURIComponent(id)}/activate`, {
      method: "POST",
    });
  },

  importPersona(file, knowledgeBaseId) {
    const form = new FormData();
    form.append(
      "file",
      new Blob([file.bytes], { type: file.type }),
      file.name,
    );
    return apiJson<ImportedPersona>(
      `${BASE}/personas/import?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}`,
      {
        method: "POST",
        body: form,
      },
    );
  },

  listPersonaAssignments() {
    return apiJson<{ data: AdapterPersonaAssignment[] }>(
      `${BASE}/persona-assignments`,
    );
  },

  updatePersonaAssignment(provider, personaId) {
    return apiJson<AdapterPersonaAssignment>(
      `${BASE}/persona-assignments/${encodeURIComponent(provider)}`,
      {
        method: "PUT",
        body: JSON.stringify({ persona_id: personaId }),
        headers: { "Content-Type": "application/json" },
      },
    );
  },
};
