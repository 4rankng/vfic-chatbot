import type { AdapterProvider } from "../../types";
import type {
  ImportedPersona,
  PersonaImportFile,
  PersonaActionsPort,
} from "./ports";

export const createPersonaActions = (port: PersonaActionsPort) => ({
  activatePersona(id: string) {
    return port.activatePersona(id);
  },

  importPersona(
    file: PersonaImportFile,
    knowledgeBaseId: string,
  ): Promise<ImportedPersona> {
    return port.importPersona(file, knowledgeBaseId);
  },

  listPersonaAssignments() {
    return port.listPersonaAssignments();
  },

  updatePersonaAssignment(provider: AdapterProvider, personaId: string | null) {
    return port.updatePersonaAssignment(provider, personaId);
  },
});
