import { usePermissions } from "ra-core";

/**
 * Derived role booleans used across the app.
 *
 * Every call site previously duplicated:
 *   const { permissions } = usePermissions();
 *   const isAdmin = permissions === "admin";
 *   const canEdit = permissions === "admin" || permissions === "recruiter";
 *
 * Consolidated here so the derivation lives in one place.
 */
export function useRoleActions() {
  const { permissions } = usePermissions();
  return {
    isAdmin: permissions === "admin",
    canEdit: permissions === "admin" || permissions === "recruiter",
  };
}
