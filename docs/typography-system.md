# Typography System

> Single source of truth for text styling across the VFIC recruiter console.
> Established 2026-07-12. Read this before adding any font size to the app.

## The scale

All typography is rem-based and centralized in `frontend/src/index.css` inside
the `@theme { ... }` block. Each token emits **both** a Tailwind utility
(`text-page-title`) **and** a `:root` CSS variable (`--fs-page-title`,
--text-page-title`) from one source — so Tailwind JSX and raw CSS share the
same scale.

### Roles

Tokens marked **[var-only]** do not generate a Tailwind utility (Tailwind v4
suppresses certain `--text-*` names). Consume them in CSS via `var(--fs-*)`.
All others emit both the utility and the CSS var.

| Role | Utility | CSS var | Desktop | Used for |
|---|---|---|---|---|
| Display | `text-display` | `--fs-display` | 24→32px (fluid) | Login hero only |
| Page title | `text-page-title` | `--fs-page-title` | 22→24px (fluid) | Every page `<h1>` / `<h2>` title |
| Metric | `text-metric` | `--fs-metric` | 20→24px (fluid) | Stat numbers (perf dashboard, ingest ring) |
| Section title | **[var-only]** | `--fs-section-title` | 16px | `<h2>` (in CSS) |
| Subsection | `text-subsection` | `--fs-subsection` | 15px | `<h3>`, small headings |
| Card title | **[var-only]** | `--fs-card-title` | 14px | Card headers (in CSS; `<CardTitle>` inherits) |
| Row title | **[var-only]** | `--fs-row-title` | 14px | List row primary text (in CSS) |
| Body | **[var-only]** | `--fs-body` | 14px | Default body text (in CSS) |
| Body small | `text-body-sm` | `--fs-body-sm` | 13px | Secondary body |
| Control | `text-control` | `--fs-control` | 14px | `<Button>` labels |
| Input | *(none — use `text-sm`)* | `--fs-input` | 14px | `<Input>`, `<Textarea>` (see collision note below) |
| Meta | `text-meta` | `--fs-meta` | 12px | Timestamps, labels |
| Caption | `text-caption` | `--fs-caption` | 11.5px | Kickers, eyebrows, helpers |
| Badge | `text-badge` | `--fs-badge` | 11.5px | `<Badge>`, chips |

> **⚠️ Naming collision warning.** Tailwind v4's `text-{name}` utility
> resolves to a **color** when a `--color-{name}` token exists. `--color-input`
> is defined (border token), so `text-input` emits `color: var(--input)` —
> NOT a font-size. Using it on `<Input>` recolors the text to the border color
> (WCAG-failing). For this reason there is **no `--text-input` token**; inputs
> use `text-sm` (which equals the 14px scale value) directly. Other unsafe
> names (all claimed by `--color-*`): foreground, background, card, popover,
> primary, secondary, muted, accent, destructive, border, ring.

### Weights / line-heights / tracking

```
--fw-regular: 400   --fw-medium: 500   --fw-semibold: 600   --fw-bold: 700
--lh-tight: 1.15    --lh-snug: 1.3     --lh-normal: 1.45    --lh-relaxed: 1.6
--tracking-tight: -0.01em   --tracking-normal: 0   --tracking-wide: 0.06em
```

## Responsive behavior

- Fixed roles (body through badge) scale uniformly via the **mobile root boost**:
  `html { font-size: 17px }` at `max-width: 767px` (in `index.css`). One knob,
  not per-token overrides.
- Fluid roles (`display`, `page-title`, `metric`) use `min(clamp(min, preferred, max), Npx)`
  with an **absolute px ceiling** so they can grow on wide screens but **never
  balloon** — even under the 17px mobile root boost. Without the px cap,
  `clamp`'s rem-based max would itself scale up (2rem × 17px = 34px), defeating
  the safeguard that killed the old 34px / 42px outliers.
- Inputs keep `font-size: 16px !important` on mobile — this is a **documented
  exception** required to prevent iOS Safari auto-zoom on focus. Do not remove it.

## Rules

1. **Never hard-code a font size.** No `text-[12px]`, no `font-size: 14px` in
   component CSS. Use a token from the scale above.
2. **Add new roles, not new sizes.** If a genuine semantic role is missing
   (e.g. "code block"), add it to the `@theme` block in `index.css` — don't
   sprinkle one-off values.
3. **Headings inherit from `@layer base`.** Only override a heading size when
   you have a documented semantic reason.
4. **Avoid `!important`** except for the iOS-zoom input rule.
5. **Color arbitrary values are fine** — `text-[var(--kb-teal)]` is a color
   reference, not a font size. The lint check ignores these.

## Intentional exceptions (documented)

| Surface | Exception | Reason |
|---|---|---|
| Login / Forgot password `<h1>` | Fraunces display face (`kb-display` class) + `text-display` | Brand identity on auth surface only |
| Knowledge center stamps | `.kb-stamp` uses Fraunces at 10.5px uppercase | Rubber-stamp status motif — branding |
| Knowledge center body | `.kb-display` / `.kb-mono` use Fraunces / IBM Plex Mono | Editorial knowledge-base identity |
| Inputs on mobile | `font-size: 16px !important` | Prevents iOS Safari focus zoom |
| Inbox sub-CSS (`personas-*.css`, `mobile-recruiting.css`, etc.) | Still uses legacy `--crm-fs-*` px tokens | **Deferred migration** — internally consistent chat surface; see "Deferred work" below |

## Deferred work

The inbox sub-CSS files (`personas-responsive.css`, `personas-project.css`,
`mobile-recruiting.css`, and ~5 others) still consume the legacy
`--crm-fs-*` / `--chat-fs-*` px-based tokens defined in
`conversations/inbox/tokens.css`. This system is **internally consistent** and
is not the source of the "oversized text" problem this migration fixed.

Unifying these files to the new `--fs-*` namespace is a follow-up task that
requires careful visual regression testing of the chat surface, which is the
app's highest-traffic UI. It should be done as a separate, focused change.

## Drift prevention

A check script at `scripts/check-typography.mjs` scans for arbitrary font-size
values and reports violations. Run it locally or wire it into CI:

```bash
node scripts/check-typography.mjs
```

Exits non-zero if any `text-[<number>]` or out-of-scale `font-size:` is found
outside the allowlist (`index.css`, `tokens.css`, documented branding files).
