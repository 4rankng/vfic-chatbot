// FIXME: This should be exported from the ra-core package
type CanAccessParams<RecordType extends Record<string, unknown> = Record<string, unknown>> = {
  action: string;
  resource: string;
  record?: RecordType;
};

// Resources visible to recruiters. Admin sees everything.
const RECRUITER_RESOURCES = new Set([
  "conversations",
  "projects",
  "contacts",
  "cases",
]);
const KNOWN_ACTIONS = new Set([
  "list",
  "show",
  "create",
  "edit",
  "delete",
  "read",
  "write",
]);

/**
 * VFIC access control.
 *
 * Recruiters can only access leads, conversations, and projects. All other
 * resources (users, bot_runs, knowledge_sources, personas, etc.) are
 * admin-only. Real enforcement is the FastAPI backend
 * (app/api/dependencies.py); this is the UX layer.
 */
export const canAccess = <
  RecordType extends Record<string, unknown> = Record<string, unknown>,
>(
  role: string,
  params: CanAccessParams<RecordType>,
  availableResources: ReadonlySet<string>,
): boolean => {
  if (!KNOWN_ACTIONS.has(params.action)) return false;
  if (!availableResources.has(params.resource)) return false;
  if (role === "admin") return true;
  if (params.resource === "contacts" && params.action === "create") return false;

  return RECRUITER_RESOURCES.has(params.resource);
};
