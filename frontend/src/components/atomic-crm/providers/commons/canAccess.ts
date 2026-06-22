// FIXME: This should be exported from the ra-core package
type CanAccessParams<
  RecordType extends Record<string, any> = Record<string, any>,
> = {
  action: string;
  resource: string;
  record?: RecordType;
};

/**
 * VFIC access control.
 *
 * admin and recruiter have identical data access EXCEPT for user management
 * (the `users` resource): only admin can manage users. Everything else is
 * available to both roles. Real enforcement is Supabase RLS; this is the
 * UX layer.
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

  // User management and the legacy configuration screen are admin-only.
  // (configuration has no backing table in VFIC — its update is a no-op —
  // so exposing it to recruiters would only surface a false success toast.)
  if (params.resource === "users" || params.resource === "configuration") {
    return false;
  }

  return true;
};
