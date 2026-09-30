/**
 * The `settings` resource: the integrations feature.
 *
 * FEATURE IS NOT CERTIFIED — this tree is deliberately flat.
 *
 * `knowledge/`, `leads/`, `projects/` and `reporting/` are
 * layered because `backend/tests/test_architecture_boundaries.py` enforces
 * them: `_FRONTEND_LAYERED_FEATURE_ROOTS` lists those roots and the test fails
 * on any outward import out of their `domain/`, `application/` and
 * `infrastructure/` directories. `integrations` is NOT in that list, so no
 * rule fires here and nothing in this directory is a layer boundary.
 *
 * The former `domain/`, `application/` and `presentation/` directories were
 * flattened on 2026-09-27 precisely because they looked like certified layers
 * while four pre-existing edges (application -> `api.ts` -> `@/lib/apiClient`,
 * domain -> `api.ts`, presentation -> `api.ts`) already broke the rules those
 * layers are meant to hold. They were never certified, so they are no longer
 * presented as layers.
 *
 * Modules here are split by ROLE, not by layer: `api.ts` is the HTTP gateway,
 * the `use*` hooks own settings state, the `*Section`/`*Field` modules render,
 * * and `providerDescriptors.ts` is the declarative provider table.
 *
 * Before re-introducing `domain/`, `application/`, `infrastructure/` or
 * `presentation/` here, finish the migration for real: give the gateway a port
 * with an adapter, keep React hooks out of `application/`, and only then add
 * `integrations` to `_FRONTEND_LAYERED_FEATURE_ROOTS`. Half a migration is
 * what this directory used to be.
 */
import { lazy } from "react";
import { KeyRound } from "lucide-react";

const SettingsConsolePage = lazy(() =>
  import("./SettingsConsolePage").then((m) => ({
    default: m.SettingsConsolePage,
  })),
);

export default {
  list: SettingsConsolePage,
  icon: KeyRound,
};
