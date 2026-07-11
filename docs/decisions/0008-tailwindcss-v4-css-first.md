# ADR-0008: TailwindCSS v4 CSS-Native Config (No JS Config)

- **Status:** Accepted
- **Date:** 2026-07-10
- **Decider:** Project lead

## Context

The frontend needs a styling system that:
- Works with shadcn/ui (new-york style) and Radix UI primitives.
- Supports a custom design token system (graphite/cloud/emerald workspace palette).
- Enables responsive layout (desktop sidebar + mobile bottom nav).
- Supports dark mode (`.dark` class).
- Minimizes build config and JS dependencies.

Options considered: TailwindCSS v3 (JS config), TailwindCSS v4 (CSS-native config), CSS Modules, vanilla-extract.

## Decision

Use **TailwindCSS v4** with CSS-native configuration (`@theme inline` in `src/index.css`), via the `@tailwindcss/vite` plugin. No `tailwind.config.js`.

Key reasons:
- **CSS-native config.** Tailwind v4 moves configuration into CSS via `@theme` — no JavaScript config file, no `content` paths to maintain. Tokens are defined where they're used.
- **Native CSS variables.** All tokens become CSS custom properties automatically, usable in any CSS context (including the workspace frame system).
- **Vite plugin.** `@tailwindcss/vite` integrates cleanly with the existing Vite 7 build — no PostCSS config needed.
- **shadcn/ui compatibility.** shadcn/ui works with Tailwind v4's CSS variables approach (`components.json` points to `src/index.css`).
- **Dark mode.** Supported via `.dark` class with OKLCH color space tokens.
- **Design token system.** The graphite/cloud/emerald palette, workspace frame tokens (spacing, radius, motion), and KB-scope tokens all live in `src/index.css` as a single source of truth.

## Consequences

- **Positive:** Zero JS config. Tokens are CSS variables (usable in any context). Single source of truth for design system. Dark mode via class toggle. Smaller build config surface.
- **Negative:** Tailwind v4 is newer with less community content than v3. Some shadcn/ui components needed migration. `@theme inline` syntax has a learning curve.
- **Neutral:** The `src/index.css` file is ~1024 lines — large but organized: font families, radius scale, shadcn color tokens, VFIC semantic accents, workspace frame system, KB-scope, dark mode.

## Related

- CSS entry: `frontend/src/index.css` (~1024 lines, all design tokens)
- Vite config: `frontend/vite.config.ts` (`@tailwindcss/vite` plugin)
- shadcn config: `frontend/components.json` (style: new-york, cssVariables: true)
- Utility: `frontend/src/lib/utils.ts` (`cn()` — clsx + tailwind-merge)
- [standards/ui-guidelines.md](../../standards/ui-guidelines.md) — UI standards
- [docs/design-tokens-graphite-cloud.md](../design-tokens-graphite-cloud.md) — current token reference
- [docs/design-tokens-warm-paper.md](../design-tokens-warm-paper.md) — superseded (reference only)
