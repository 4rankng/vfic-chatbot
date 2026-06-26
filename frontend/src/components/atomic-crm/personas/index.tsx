import type { Persona } from "../types";
import { PersonaList } from "./PersonaList";
import { PersonaCreate } from "./PersonaCreate";
import { PersonaEdit } from "./PersonaEdit";

// Agent personas (the bot's voice). Free-form markdown body; several stored,
// one global persona active at a time. Seeded from persona.md on first boot.
export default {
  list: PersonaList,
  create: PersonaCreate,
  edit: PersonaEdit,
  recordRepresentation: (record?: Persona) => record?.name ?? "Persona",
};
