/**
 * Paths the registry must never publish, because an external dependency owns
 * them.
 *
 * Two scripts have to agree on this list, and disagreeing is expensive in both
 * directions:
 *
 * - `check-registry-paths.mjs` allows a *published* file to import one of these
 *   without the import counting as an "unpublished local dependency".
 * - `generate-registry.mjs` must NOT publish them: they are supplied by the
 *   external shadcn registry (`components/admin`, `components/ui`,
 *   `hooks/use-mobile.ts`, `lib/utils.ts`) or installed by the Untitled UI CLI
 *   (`components/base`, `components/foundations`, `utils`, the resize-observer
 *   hook). Publishing them would ship a second copy of a dependency to every
 *   consumer of this registry.
 *
 * On 2026-09-28 they did disagree: the checker was told the CLI's
 * `hooks/use-resize-observer.ts` was dependency-owned, while the generator's
 * `src/hooks/**` glob published it. The list lives here now so a path is either
 * owned or published, never both.
 *
 * Entries are either a directory (trailing slash, matched as a prefix) or a
 * single file, relative to the frontend root.
 */
export const DEPENDENCY_OWNED_PATHS = [
  "src/components/admin/",
  "src/components/ui/",
  "src/components/base/",
  "src/components/foundations/",
  "src/utils/",
  "src/hooks/use-mobile.ts",
  "src/hooks/use-resize-observer.ts",
  "src/lib/utils.ts",
];

/** True when `file` is supplied by a dependency rather than this application. */
export const isDependencyOwned = (file) =>
  DEPENDENCY_OWNED_PATHS.some(
    (owned) => file === owned || file.startsWith(owned),
  );
