// FIXME: This should be exported from the ra-core package
type CanAccessParams<
  RecordType extends Record<string, any> = Record<string, any>,
> = {
  action: string;
  resource: string;
  record?: RecordType;
};

// Resources visible to recruiters. Admin sees everything.
const RECRUITER_RESOURCES = new Set(["leads", "conversations", "projects"]);

/**
 * VFIC access control.
 *
 * Recruiters can only access leads, conversations, and projects. All other
 * resources (users, bot_runs, knowledge_sources, personas, etc.) are
 * admin-only. Real enforcement is the FastAPI backend
 * (app/api/dependencies.py); this is the UX layer.
 */
export const canAccess = <
  RecordType extends Record<string, any> = Record<string, any>,
>(
  role: string,
  params: CanAccessParams<RecordType>,
) => {
  if (role === "admin") {
    return true;
  }

  return RECRUITER_RESOURCES.has(params.resource);
};
