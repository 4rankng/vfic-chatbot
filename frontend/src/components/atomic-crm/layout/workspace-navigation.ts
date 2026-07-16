import type { CompiledDestination } from "../capabilities/types";

export type WorkspaceRole = "admin" | "recruiter";
export type WorkspaceNavigationSurface = "rail" | "mobile";
export type WorkspaceDestination = CompiledDestination;
type WorkspaceLinkDestination = Pick<WorkspaceDestination, "id" | "to">;

export const normalizeWorkspacePath = (value: string): string => {
  const hashPath = value.startsWith("#") ? value.slice(1) : value;
  const path = hashPath.split(/[?#]/, 1)[0] || "/";
  return path.startsWith("/") ? path : `/${path}`;
};

export const getWorkspaceDestinations = (
  role: WorkspaceRole,
  surface: WorkspaceNavigationSurface,
  compiledDestinations: readonly WorkspaceDestination[],
): readonly WorkspaceDestination[] =>
  compiledDestinations.filter(
    (destination) =>
      destination[surface] &&
      (!destination.roles || destination.roles.includes(role)) &&
      (surface !== "mobile" ||
        (role === "admin"
          ? destination.id !== "account"
          : destination.id !== "settings" && destination.id !== "performance")),
  );

export const getWorkspaceOverflowDestinations = (
  role: WorkspaceRole,
  compiledDestinations: readonly WorkspaceDestination[],
): readonly WorkspaceDestination[] => {
  const primaryIds = new Set(
    getWorkspaceDestinations(role, "mobile", compiledDestinations).map(
      ({ id }) => id,
    ),
  );
  return compiledDestinations.filter(
    (destination) =>
      (destination.rail || destination.mobile) &&
      (!destination.roles || destination.roles.includes(role)) &&
      !primaryIds.has(destination.id),
  );
};

/** A non-zero inbox badge opens the authoritative server-filtered reply queue. */
export const getWorkspaceDestination = (
  destination: WorkspaceLinkDestination,
  attentionCount: number,
): string =>
  destination.id === "messages" && attentionCount > 0
    ? `${destination.to}?needs_attention=true`
    : destination.to;
