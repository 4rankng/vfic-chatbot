# Upstream sync — Atomic CRM fork posture

> **TL;DR — VFIC is a permanent fork of Atomic CRM. Never re-run the whole
> registry block (`npx shadcn add …/atomic-crm.json -o`); it would clobber every
> VFIC customization. Sync individual primitives only, from `ui.shadcn.com`.**

## Status

VFIC diverged from [Atomic CRM](https://marmelab.com/atomic-crm/) (marmelab) and
from the companion [shadcn-admin-kit](https://marmelab.com/shadcn-admin-kit/).
The divergence is large and intentional:

- **Resources replaced.** Upstream `contacts`, `companies`, `deals`, `tags`,
  `tasks`, `notes`, `sales` were **deleted**. VFIC uses `leads`, `conversations`,
  `bot_runs`, `knowledge_sources`, `users` against a live VFIC Supabase schema.
- **Vietnamese-only UI** (custom locale catalog; the language switcher is removed).
- **Custom providers** (`src/components/atomic-crm/providers/supabase/`) bound to
  the VFIC schema.
- **Overhauled UX**: topbar glass-pill + command palette, `/leads` overhaul,
  virtualized conversations, responsive layout.
- **OKLCH design tokens** (`src/index.css`; see
  [`../adr/ADR-oklch-token-convention.md`](../adr/ADR-oklch-token-convention.md)).

Because of this, **a block-level re-sync is not viable** — it would overwrite all
of the above. Treat this repo as a permanent fork.

## What you MAY sync

`src/components/ui/` and `src/components/admin/` are **mutable dependencies** —
they mirror upstream shadcn / shadcn-admin-kit and are meant to be edited in
place. Refresh a single primitive like this:

```bash
# One primitive at a time, from the canonical registry:
npx shadcn add <component-name>
```

Then **diff** the change and re-apply any VFIC patch that lived in that file
(most primitives are stock; a few — e.g. the custom `Item` compound, `Spinner` —
may carry local edits).

## What you MUST NOT sync

Never run:

```bash
npx shadcn add https://marmelab.com/atomic-crm/r/atomic-crm.json -o   # ❌
```

The `-o` (overwrite) on the whole block rewrites ~150 files, including every
locked path below.

## Locked paths

The machine-readable list lives in
[`.vfic-overrides.json`](../.vfic-overrides.json). Summary:

| Area | Path | Why it's locked |
|---|---|---|
| Tokens | `src/index.css` | OKLCH design tokens |
| Entry/config | `src/App.tsx`, `src/main.tsx`, `src/lib/vfic/**` | VFIC config wiring |
| Root/resources | `src/components/atomic-crm/root/**` | Resource list, configuration context |
| Layout/topbar | `src/components/atomic-crm/layout/**` | Glass-pill, command palette, Header/MobileHeader |
| Feature pages | `…/leads/**`, `…/conversations/**`, `…/dashboard/**`, `…/settings/**`, `…/login/**` | VFIC overhauls |
| Providers | `src/components/atomic-crm/providers/**` | VFIC Supabase dataProvider/authProvider, vi i18n |
| Branding | `public/light-logo.png`, `public/dark-logo.png`, `public/logos/**` | VFIC logos |

## Baseline pin

- Upstream registry: `https://marmelab.com/atomic-crm/r/atomic-crm.json`
- Admin kit registry: `https://marmelab.com/shadcn-admin-kit/r/admin.json`
- shadcn style: `new-york` (see `components.json`)
- **TODO:** record the upstream Atomic CRM commit this fork diverged from
  (`.vfic-overrides.json → fork.pinUpstreamCommit`). Determine it with
  `git log` on the earliest VFIC edit under
  `src/components/atomic-crm/root/CRM.tsx`.

## Pre-commit note

`make registry-gen` regenerates `frontend/registry.json` additively from file
globs. It is safe, but review the diff before committing — it should only ever
**add** entries, never drop VFIC files.
