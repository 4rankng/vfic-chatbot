import { lazy } from "react";
import type { Persona } from "../types";

const PersonaList = lazy(() =>
  import("./PersonaList").then((m) => ({ default: m.PersonaList })),
);
const PersonaCreate = lazy(() =>
  import("./PersonaCreate").then((m) => ({ default: m.PersonaCreate })),
);
const PersonaEdit = lazy(() =>
  import("./PersonaEdit").then((m) => ({ default: m.PersonaEdit })),
);

// Agent personas (the bot's voice). Free-form markdown body; several stored,
// one global persona active at a time. Seeded from persona.md on first boot.
export default {
  list: PersonaList,
  create: PersonaCreate,
  edit: PersonaEdit,
  recordRepresentation: (record?: Persona) => record?.name ?? "Agent",
};
