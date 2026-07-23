import { createPersonaActions } from "./application/personaActions";
import { personaActionsApi } from "./infrastructure/personaActionsApi";

const actions = createPersonaActions(personaActionsApi);

export const activatePersona = actions.activatePersona;
export const listPersonaAssignments = actions.listPersonaAssignments;
export const updatePersonaAssignment = actions.updatePersonaAssignment;
export const importPersona = async (file: File, knowledgeBaseId: string) =>
  actions.importPersona(
    {
      name: file.name,
      type: file.type,
      bytes: await file.arrayBuffer(),
    },
    knowledgeBaseId,
  );
