import { useEffect, useRef, useState } from "react";

type HasId = { id: string | number };

/** Stable default accessor — defined once so the effect below never re-runs
 *  merely because an inline fallback was recreated on each render. */
const defaultIdOf = <T extends HasId>(item: T): string => String(item.id);

/**
 * Manages a master-detail selection that auto-syncs with a data list.
 *
 * Replaces the duplicated selection-sync useEffect pattern found in
 * ProjectList and KnowledgeSourceList. Core behavior:
 *  - auto-clears when data is empty
 *  - auto-selects the first item when the current selection becomes stale
 *  - when `autoSelectNewlyAppeared` is true, selects the first item that
 *    appears in `data` that wasn't present on the previous render (used by
 *    KnowledgeSourceList to surface freshly-uploaded documents).
 */
export function useMasterDetailSelection<T extends HasId>({
  data,
  getId,
  autoSelectNewlyAppeared = false,
}: {
  data: T[];
  getId?: (item: T) => string;
  autoSelectNewlyAppeared?: boolean;
}) {
  const idOf = getId ?? defaultIdOf;
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Track IDs we've seen to detect newly appeared items. Seeded with the first
  // data batch so the initial load doesn't count as "newly appeared".
  const knownIdsRef = useRef<Set<string>>(new Set(data.map(idOf)));
  const firstLoadRef = useRef(true);

  useEffect(() => {
    if (data.length === 0) {
      setSelectedId(null);
      return;
    }

    const currentIds = data.map(idOf);
    const currentIdSet = new Set(currentIds);

    // Detect newly appeared items (for autoSelectNewlyAppeared) on subsequent
    // renders — the first render only seeds the known set.
    if (autoSelectNewlyAppeared) {
      if (firstLoadRef.current) {
        firstLoadRef.current = false;
      } else {
        const appeared = currentIds.filter(
          (id) => !knownIdsRef.current.has(id),
        );
        if (appeared.length > 0) {
          setSelectedId(appeared[0]);
        }
      }
    }

    // Clear selection if it's no longer in the data.
    if (selectedId !== null && !currentIdSet.has(selectedId)) {
      setSelectedId(currentIds[0]);
    }

    knownIdsRef.current = currentIdSet;
  }, [data, selectedId, idOf, autoSelectNewlyAppeared]);

  return { selectedId, setSelectedId };
}
