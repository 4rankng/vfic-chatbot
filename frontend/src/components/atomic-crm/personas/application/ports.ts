import type {
  AdapterPersonaAssignment,
  AdapterProvider,
  PersonaFollowupRules,
} from "../../types";

export type ImportedPersona = {
  name: string;
  body_md: string;
  notes?: string | null;
  followup_rules?: PersonaFollowupRules;
};

export interface PersonaActionsPort {
  activatePersona(id: string): Promise<void>;
  importPersona(file: File, knowledgeBaseId: string): Promise<ImportedPersona>;
  listPersonaAssignments(): Promise<{ data: AdapterPersonaAssignment[] }>;
  updatePersonaAssignment(
    provider: AdapterProvider,
    personaId: string | null,
  ): Promise<AdapterPersonaAssignment>;
}
