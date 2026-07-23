import { createPersonaActions } from "./application/personaActions";
import { personaActionsApi } from "./infrastructure/personaActionsApi";

export const {
  activatePersona,
  importPersona,
  listPersonaAssignments,
  updatePersonaAssignment,
} = createPersonaActions(personaActionsApi);
