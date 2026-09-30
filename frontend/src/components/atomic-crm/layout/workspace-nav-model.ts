import type {
  CompiledDestination,
  DestinationSection,
} from "../capabilities/types";

export type WorkspaceRole = "admin" | "recruiter";
export type WorkspaceDestination = CompiledDestination;

/**
 * One sidebar group. The compiled contract carries the section id and this
 * module owns its heading, so section copy changes here without touching a
 * capability contribution.
 */
export type WorkspaceSection = Readonly<{
  id: DestinationSection;
  label: string;
  items: readonly WorkspaceDestination[];
}>;

const SECTION_ORDER: readonly DestinationSection[] = [
  "operations",
  "team",
  "system",
];

const SECTION_LABELS: Record<DestinationSection, string> = {
  operations: "Vận hành",
  team: "Đội ngũ & Agent",
  system: "Hệ thống",
};

export const normalizeWorkspacePath = (value: string): string => {
  const hashPath = value.startsWith("#") ? value.slice(1) : value;
  const path = hashPath.split(/[?#]/, 1)[0] || "/";
  return path.startsWith("/") ? path : `/${path}`;
};

/** Every destination the role may reach, in declaration order. */
export const getWorkspaceDestinations = (
  role: WorkspaceRole,
  compiledDestinations: readonly WorkspaceDestination[],
): readonly WorkspaceDestination[] =>
  compiledDestinations.filter(
    (destination) => !destination.roles || destination.roles.includes(role),
  );

/** Destinations grouped into sidebar sections; empty sections are dropped. */
export const getWorkspaceSections = (
  role: WorkspaceRole,
  compiledDestinations: readonly WorkspaceDestination[],
): readonly WorkspaceSection[] => {
  const reachable = getWorkspaceDestinations(role, compiledDestinations);

  return SECTION_ORDER.map((id) => ({
    id,
    label: SECTION_LABELS[id],
    items: reachable.filter((destination) => destination.section === id),
  })).filter((section) => section.items.length > 0);
};

/**
 * A non-zero inbox badge opens the authoritative server-filtered reply queue,
 * so the badge and the link it decorates always describe the same rows.
 */
export const getWorkspaceDestination = (
  destination: Pick<WorkspaceDestination, "id" | "to">,
  attentionCount: number,
): string =>
  destination.id === "messages" && attentionCount > 0
    ? `${destination.to}?needs_attention=true`
    : destination.to;
