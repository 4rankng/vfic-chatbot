# UI / UX Guidelines

> Frontend design standards for the ChatBot (VFIC miniCRM) recruiter console.
> For the full design token reference, see
> [`../docs/design-tokens-graphite-cloud.md`](../docs/design-tokens-graphite-cloud.md).

## Design Token System

The authenticated workspace uses the **graphite / cloud / emerald** palette:

| Role | Token | Value |
|---|---|---|
| Application shell | `--workspace-shell` | `#0F172A` (slate-900) |
| Main canvas | `--workspace-canvas` | `#EEF2F6` |
| Surfaces | `--workspace-surface` | white / flat |
| Text | `--workspace-ink` / `--workspace-ink-muted` | slate scale |
| Borders | `--workspace-border` | slate-200 |
| Brand / focus / actions | `--workspace-action` / `--workspace-focus` | emerald (`#0F8A68`) |

**Usage guidance:**
- Shell (`#0F172A`) only for navigation surfaces (sidebar, top bar).
- White surfaces stay flat and are separated with borders, spacing, and tonal
  backgrounds — default to canvas where a surface is not needed.
- Do not use drop shadows, inset highlights, or hover/active lift effects.
  Preserve keyboard focus with a visible outline instead.
- Emerald for selection, focus rings, primary actions, and healthy status only.

> **Note:** `docs/design-tokens-warm-paper.md` is **superseded** (replaced 2026-07-10). Do not use warm-paper tokens. It remains for reference only.

## Component Library

- **shadcn/ui (new-york style).** Primitives in `frontend/src/components/ui/` (35 components). Managed by `npx shadcn` — registry config in `components.json`.
- **Radix UI primitives** underneath. Always use Radix for dialogs, popovers, dropdowns, tooltips — never reinvent.
- **Lucide icons.** The only icon library. Do not mix icon sets.
- **class-variance-authority (CVA).** Use CVA for component variants. Pattern: `cva(base, { variants: {...}, defaultVariants: {...} })`.
- **`cn()` utility.** From `lib/utils.ts` — `clsx` + `tailwind-merge`. Always use for conditional classes.

## Workspace Frame System

The CSS in `src/index.css` defines a comprehensive workspace frame:

- **Desktop sidebar:** `minmax(13rem, 17rem)` wide, collapses to `4.25rem` on medium screens.
- **Mobile bottom navigation:** grid, 4–5 columns, safe-area-aware (`env(safe-area-inset-bottom)`).
- **Spacing scale:** `space-1` through `space-6`.
- **Radius tokens:** `control`, `panel`.
- **Motion tokens:** `fast: 160ms`, `standard: 240ms`.

The Layout component (`atomic-crm/layout/Layout.tsx`) detects route-based workspace types (dashboard, conversation, knowledge, integration, persona, project, profile) and applies full-height or constrained-width layouts accordingly.

## Typography

- **Sans:** Inter (via `@fontsource-variable/inter`).
- **Display:** Big Shoulders Display.
- **Mono:** IBM Plex Mono.

## Vietnamese-First i18n

- **Default locale:** Vietnamese (`"vi"`).
- **Available locales:** `[{ locale: "vi", name: "Tiếng Việt" }]` — only Vietnamese is user-selectable.
- **All user-facing strings must be in Vietnamese.** Add new strings to `vietnameseCrmMessages.ts`.
- **`allowMissing: true`** — missing keys fall through without error, but always provide the Vietnamese translation.
- **Error messages** in the API client (`api.ts:friendlyApiMessage`) are in Vietnamese.

## Accessibility

- Use semantic HTML (`<nav>`, `<main>`, `<aside>`, `<button>`) — not `<div>` with click handlers.
- Provide ARIA labels for icon-only buttons.
- Ensure keyboard navigation works (tab order, focus rings via emerald token).
- Maintain WCAG 2.2 AA contrast ratios (see `docs/design-tokens-warm-paper.md` for the contrast table methodology — apply the same checks to graphite-cloud tokens).

## Mobile Responsiveness

- **Bottom navigation** is the primary mobile nav (grid, 4–5 columns, safe-area-aware).
- **Touch targets** must be at least 44×44px.
- **Virtualization** required for long lists: use `virtua` (`VList`) (conversations, messages). Never render unbounded lists.
- **Test on mobile viewport** before declaring done.
