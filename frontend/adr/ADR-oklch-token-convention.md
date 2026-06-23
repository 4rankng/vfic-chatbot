# ADR: OKLCH design-token convention

- **Status:** Accepted
- **Date:** 2026-06-23
- **Scope:** `src/index.css` design tokens (shadcn semantic set + VFIC brand set)

## Context

The frontend ships on Tailwind v4 + shadcn v4, but the design tokens in
`src/index.css` were authored in hex/rgba (`--primary: #e0701f`,
`--border: rgba(20,32,42,0.09)`, …). Upstream shadcn v4 primitives and the
canonical `ui.shadcn.com` registry ship tokens in **OKLCH**. Keeping hex is not a
bug — Tailwind v4 opacity modifiers (`bg-primary/50`) compile to
`color-mix(in oklab, var(--color-primary) 50%, transparent)`, which works with any
color format — so the motivation is alignment + capability, not a fix:

- **Upstream alignment:** matching OKLCH makes future primitive syncs from
  `ui.shadcn.com` diff-clean.
- **Perceptual color ops:** OKLCH unlocks `color-mix()` and relative-color syntax
  for perceptually-uniform tints/shades.

VFIC's palette is deliberately designed (warm off-white background, orange
primary, steel/ember/green accents). The risk was **over-converting** — swapping
the hand-tuned neutrals for generic shadcn defaults would homogenise a
distinctive brand.

## Decision

Convert every token to OKLCH using a **three-tier convention** that preserves the
existing design intent:

### Tier A — Solids (zero visible change)

All opaque semantic + brand tokens are replaced by their **exact sRGB→OKLCH
equivalent** (`oklch(L C H)`). Alpha tokens that must stay transparent
(`--border`, `--input`, `--grid-color`, `--shimmer-highlight`,
`--sidebar-border`) become `oklch(L C H / <alpha>)` with the original alpha
preserved. The original hex/rgba is kept in a trailing comment for brand
reference. On-screen these are pixel-identical to the prior hex values.

### Tier B — Soft brand tints (the one intended visible change)

`--color-amber-soft` and `--color-ember-soft` were alpha-rgba over an unknown
surface (`rgba(224,112,31,0.13)`, `rgba(214,54,42,0.12)`), so their appearance
varied with whatever sat underneath. They are replaced by perceptual
`color-mix(in oklab, … , var(--background))` tints that resolve per-theme:

```css
--color-amber-soft: color-mix(in oklab, var(--primary) 13%, var(--background));
--color-ember-soft: color-mix(in oklab, oklch(0.5785 0.1984 29.0) 12%, var(--background));
```

`--primary` and `--background` are real `:root` CSS variables, so they resolve at
runtime per light/dark. `--color-ember` is referenced by its raw OKLCH because
`@theme inline` tokens are inlined into utilities and are **not** emitted as
runtime CSS variables (so `var(--color-ember)` would not resolve).

### Tier C — Structural

`body::before` gradient stops and any remaining `rgba()` were converted to
`oklch(… / <alpha>)` for a single consistent color space.

## Alternatives considered

- **Keep hex/rgba.** Zero effort, zero risk, but diverges from upstream shadcn and
  forgoes perceptual color ops. Rejected for alignment reasons.
- **Full retune to the shadcn `neutral` OKLCH palette** (overwrite VFIC neutrals
  with generic defaults). Rejected: it would flatten a distinctive, intentional
  brand. This ADR's Tier A explicitly preserves the exact VFIC palette.
- **Widen Tier B** (also retune `--grid-color`, `--shimmer-highlight`,
  `--border`). Rejected: those are full-page or single-surface overlays, so the
  alpha-vs-mix difference is negligible; keeping them exact (Tier A) minimises
  visible change. Only the two brand soft-tints genuinely benefit.

## Consequences

- **Positive:** unified OKLCH color space; cleaner future primitive syncs; the two
  soft-tints are now theme-aware and consistent across surfaces.
- **Negative / trade-off:** Tier B changes `--color-amber-soft`/`--color-ember-soft`
  slightly in dark mode (more intentional, but a visible change). It is gated
  behind the visual harness and trivially revertible to the exact-equivalent
  `oklch(… / 0.13)` form.
- **Validation:** the visual regression harness (`e2e/visual.spec.ts`, login-page
  baseline) confirmed Tier A is pixel-exact — the post-conversion build matched
  the pre-conversion baseline with zero diff. Tier B surfaces are not on the login
  page; they are validated by construction (deterministic `color-mix`).

## Follow-ups

- Add authenticated-page visual baselines (requires local Supabase or an e2e auth
  fixture) so the Tier B soft-tints and `--chart-*` tokens are screenshot-covered.
- Optionally add `prettier-plugin-tailwindcss` for stable class ordering (not
  required for correctness).
