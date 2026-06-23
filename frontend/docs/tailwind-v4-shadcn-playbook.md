# Tailwind v4 + shadcn playbook (VFIC frontend)

A maintainer's reference for how the styling stack is wired and how to change it
safely. Read once; refer back when touching theme, tokens, primitives, or visual
tests.

## 1. Architecture

- **Tailwind v4** via the **`@tailwindcss/vite`** plugin (`vite.config.ts`).
  - There is **no** `tailwind.config.*` and **no** `postcss.config.*` — v4 is
    configured CSS-first.
- **Single CSS entry:** `src/index.css` (imported first by `src/main.tsx`).
  - `@import "tailwindcss";` (v4 syntax; not the v3 `@tailwind base/components/utilities`).
  - `@custom-variant dark (&:is(.dark *));` — dark mode is a `.dark` class on `<html>`.
  - `@theme inline { … }` maps the semantic tokens to Tailwind color utilities
    (`--color-primary: var(--primary)` → powers `bg-primary`, `text-primary`, …).
- **Design tokens** live in plain `:root` / `.dark` blocks (real CSS variables,
  theme-switchable). `@theme inline` references them so utilities stay live across
  light/dark.
- **shadcn/ui** — `new-york` style (see `components.json`), `@/` → `src/` alias.
  Primitives in `src/components/ui/` (34 files), Radix-backed, use `cn()` from
  `@/lib/utils` (`twMerge(clsx(…))`) and `class-variance-authority` where variants
  exist. `data-slot` attributes throughout (modern shadcn pattern).
- **Theme switching** is driven by `localStorage["theme"]` via ra-core's store,
  default `"system"` (follows `prefers-color-scheme`). See
  `src/components/admin/theme-provider.tsx`.

## 2. Token map & OKLCH convention

Tokens are **OKLCH** (`src/index.css`). The convention is three tiers — see
[`../adr/ADR-oklch-token-convention.md`](../adr/ADR-oklch-token-convention.md) for
the full rationale.

| Tier | Applies to | Rule | Visible change |
|---|---|---|---|
| **A — Solids** | All opaque semantic + brand tokens; alpha overlays (`--border`, `--grid-color`, …) | Exact sRGB→OKLCH equivalent: `oklch(L C H)` or `oklch(L C H / a)`. Original hex kept in a trailing comment. | None (pixel-exact, verified by the visual harness) |
| **B — Soft tints** | `--color-amber-soft`, `--color-ember-soft` | Perceptual `color-mix(in oklab, … , var(--background))`, theme-aware | Intended minimal change (cleaner in dark mode) |
| **C — Structural** | `body::before` gradient stops | `oklch(… / a)` | None-to-marginal |

**Why OKLCH at all?** Not a bugfix — Tailwind v4 opacity modifiers already work
with hex via `color-mix(in oklab, …)`. OKLCH is for **upstream alignment** (cleaner
primitive syncs) and **perceptual color ops** (`color-mix`, relative-color).

**Gotcha:** `@theme inline` tokens are inlined into utilities and are **not**
emitted as runtime CSS variables. So `--color-ember-soft` cannot reference
`var(--color-ember)` (it doesn't exist at runtime). It references raw OKLCH
instead. `var(--primary)` / `var(--background)` work because those are real
`:root` variables.

### Adding a new color token

1. Add the var to `:root` (and `.dark` if it differs by theme): `--my-token: oklch(L C H); /* #hex */`.
2. Expose it as a utility in `@theme inline`: `--color-my-token: var(--my-token);`
   (omit the `var()` wrapper and just inline the value if it should be static,
   like the brand solids).
3. Now `bg-my-token`, `text-my-token`, `border-my-token` all work.

## 3. Adding / updating a shadcn primitive

Sync **one primitive at a time** from the canonical `ui.shadcn.com` registry into
`src/components/ui/` (or `src/components/admin/` for admin-kit). **Never** re-run
the whole Atomic CRM block — see
[`upstream-sync.md`](upstream-sync.md).

```bash
npx shadcn add <component-name>     # e.g. npx shadcn add popover
git diff src/components/ui/<component>.tsx   # review; re-apply any VFIC patch
```

## 4. Visual regression harness

`e2e/visual.spec.ts` captures screenshot baselines via Playwright
`toHaveScreenshot`. The app is served from the **e2e production build** (the
webServer runs `vite preview` against `dist/`).

```bash
# One-time (and after any change that affects the built bundle):
npm run build:e2e

# Run the visual tests:
npx playwright test visual

# Capture/update baselines after an INTENTIONAL visual change:
npx playwright test visual --update-snapshots
```

Baselines live in `e2e/visual.spec.ts-snapshots/` (filenames encode
`<route>-<theme>-<project>-<platform>.png`). Projects: `visual-desktop`,
`visual-mobile`.

**Coverage today:** the **login page** (unauthenticated, fully deterministic,
zero-backend). It covers the core token surface — background, foreground, primary
(orange), card, border, input, logos, split-panel — so it reliably catches
token-level regressions.

**Authenticed pages (dashboard/leads/conversations):** not yet baselined — they
need an authenticated session + data, which requires local Supabase (the
`.env.e2e` path). This is the documented Tier-2 extension. To add them:
1. Start local Supabase and seed a test admin (`supabase start`; seed profiles).
2. In the spec, log in (or inject a session) and add entries to a route list
   mirroring `e2e/vfic.spec.ts` (which is currently `.fixme` for the same reason).

**Determinism** (handled in the spec): telemetry + Supabase calls
short-circuited; service-worker registration neutered; fonts awaited;
animations disabled; theme driven via `prefers-color-scheme` + forced `.dark` class.

## 5. Fork posture

Permanent fork of Atomic CRM. Locked paths and sync rules:
[`upstream-sync.md`](upstream-sync.md) + [`.vfic-overrides.json`](../.vfic-overrides.json).

## 6. Quick command reference

```bash
# Dev
npm run dev

# Typecheck / build
npm run typecheck            # tsc --noEmit
npm run build                # tsc && vite build

# Visual regression
npm run build:e2e
npx playwright test visual
npx playwright test visual --update-snapshots

# Sync ONE shadcn primitive (never the whole block)
npx shadcn add <component-name>

# Registry (auto-runs on pre-commit; safe, additive)
make registry-gen
```
