# Typography System

> Single source of truth for text styling across the VFIC recruiter console.
> Established 2026-07-12. Revised 2026-07-19 (all frontend surfaces migrated,
> legacy exemptions removed, and inline-style enforcement added). Read this
> before adding any font size to the app.

## The scale

All typography is rem-based and centralized in `frontend/src/index.css` inside
the `@theme { ... }` block. Each token emits **both** a Tailwind utility
(`text-page-title`) **and** a `:root` CSS variable (`--fs-page-title`,
--text-page-title) from one source — so Tailwind JSX and raw CSS share the
same scale. The inbox/workspace CSS aliases (`--crm-fs-*`, `--chat-fs-*` in
`conversations/inbox/tokens.css`) point at these same `--fs-*` vars, so there
is exactly **one** scale, not two.

### Roles

Tokens marked **[var-only]** do not generate a Tailwind utility (Tailwind v4
suppresses certain `--text-*` names). Consume them in CSS via `var(--fs-*)`.
All others emit both the utility and the CSS var.

Desktop sizes shown; see "Responsive behavior" for the mobile scale.

| Role | Utility | CSS var | Desktop | Used for |
|---|---|---|---|---|
| Display | `text-display` | `--fs-display` | 24→32px (fluid) | Login hero only |
| Page title | `text-page-title` | `--fs-page-title` | 22→28px (fluid) | Every page `<h1>` / `<h2>` title |
| Metric | `text-metric` | `--fs-metric` | 20→24px (fluid) | Stat numbers (perf dashboard, ingest ring) |
| Content title | `text-content-title` | `--fs-content-title` | 20px | Panel/content titles, dialog/page `<h2>` |
| Section title | `text-section-title` | `--fs-section-title` | 20px | `<h3>` section headings inside a page |
| Subsection | `text-subsection` | `--fs-subsection` | 18px | `<h4>`, sub-headings, header/product titles |
| Nav | `text-nav` | `--fs-nav` | 15px | Sidebar nav items, step nav labels |
| Card title | `text-card-title` | `--fs-card-title` | 14px | `<CardTitle>`, card/row headers |
| Row title | `text-row-title` | `--fs-row-title` | 14px | List row primary text |
| Body | `text-body` | `--fs-body` | 14px | Default body text, paragraphs |
| Body large | `text-body-lg` | `--fs-body-lg` | 16px | Emphasized body copy and spacious empty states |
| Body small | `text-body-sm` | `--fs-body-sm` | 13px | Secondary body, item descriptions |
| Control | `text-control` | `--fs-control` | 14px | `<Input>`/`<Select>`/`<Textarea>` control text |
| Label | `text-label` | `--fs-label` | 14px | Form field labels (weight 600) |
| Button | `text-button` | `--fs-button` | 14px | `<Button>` labels (weight 600) |
| Helper | `text-helper` | `--fs-helper` | 12px | Helper text, descriptions, metadata (lh 1.5) |
| Meta | `text-meta` | `--fs-meta` | 12px | Timestamps, fine metadata |
| Caption | `text-caption` | `--fs-caption` | 11.5px | Kickers, eyebrows |
| Badge | `text-badge` | `--fs-badge` | 11.5px | `<Badge>`, chips |

> **⚠️ Naming collision warning.** Tailwind v4's `text-{name}` utility
> resolves to a **color** when a `--color-{name}` token exists. `--color-input`
> is defined (border token), so `text-input` emits `color: var(--input)` —
> NOT a font-size. Using it on `<Input>` recolors the text to the border color
> (WCAG-failing). For this reason there is **no `--text-input` token**; inputs
> use `text-control` directly. Other unsafe names (all claimed by `--color-*`):
> foreground, background, card, popover, primary, secondary, muted, accent,
> destructive, border, ring.

### Weights / line-heights / tracking

```
--fw-regular: 400   --fw-medium: 500   --fw-semibold: 600   --fw-bold: 700
--lh-tight: 1.15    --lh-snug: 1.3     --lh-normal: 1.45    --lh-relaxed: 1.6
--tracking-tight: -0.01em   --tracking-normal: 0   --tracking-wide: 0.06em
```

Weight is **not** carried by a text token (a `--text-*` token only sets
font-size + line-height + letter-spacing). Set weight explicitly with the
matching `font-*` utility: labels and buttons use `font-semibold` (600), nav
items `font-medium` (500), body `font-normal`/regular (400).

## Responsive behavior

The root font-size is **fixed at 16px** (`html { font-size: 16px }` in the
`@layer base` block of `index.css`). It does not change between desktop and
mobile, so rem math is identical everywhere and predictable.

- **Mobile scale** is applied by a single centralized override at
  `@media (max-width: 767px) { :root { --text-*: ... } }` in `index.css`. Each
  role steps down (page-title→22px, section-title→18px, nav→13px, body→14px,
  helper→12px). Components do **not** set their own mobile font sizes — they
  inherit the token.
- **Form controls on touch** (`input`/`textarea`/`select`) are kept at 16px on
  mobile via the `text-control`/`text-label` tokens (overridden to 1rem in the
  mobile `:root` block), which prevents iOS Safari from auto-zooming the
  viewport on focus. No `!important` is used.
- **PWA text inflation** is controlled by `html { -webkit-text-size-adjust: 100%;
  text-size-adjust: 100% }` — users can still pinch-zoom, but the browser will
  not auto-inflate text in landscape/PWA mode.
- **Form controls inherit the document font** via `button, input, select,
  textarea { font: inherit }`, so the UA stylesheet's default control fonts no
  longer leak in.

## Rules

1. **Never hard-code a font size.** No `text-sm`/`text-[12px]`/`font-size: 14px`
   in component code. Use a token from the scale above. (Raw Tailwind sizes
   like `text-sm` were swept out of the codebase in the 2026-07-15 migration.)
2. **Add new roles, not new sizes.** If a genuine semantic role is missing
   (e.g. "code block"), add it to the `@theme` block in `index.css` — don't
   sprinkle one-off values.
3. **Headings inherit from `@layer base`.** Only override a heading size when
   you have a documented semantic reason.
4. **Avoid `!important`** for typography. The legacy mobile input-zoom `!important`
   hack was removed in favor of the `font: inherit` reset + 16px touch tokens.
5. **Color arbitrary values are fine** — `text-[var(--kb-teal)]` is a color
   reference, not a font size. The lint check ignores these.
6. **Set weight explicitly.** Pair a size token with the matching `font-*`
   utility; don't rely on inherited weight for primary text like labels/buttons.

## Intentional exceptions (documented)

| Surface | Exception | Reason |
|---|---|---|
| Login / Forgot password `<h1>` | Fraunces display face (`kb-display` class) + `text-display` | Brand identity on auth surface only |
| Knowledge center stamps | `.kb-stamp` uses Fraunces at 10.5px uppercase | Rubber-stamp status motif — branding |
| Knowledge center body | `.kb-display` / `.kb-mono` use Fraunces / IBM Plex Mono | Editorial knowledge-base identity |

## Dual scale (retired 2026-07-15)

The inbox/workspace CSS previously held a parallel px-based scale
(`--crm-fs-*` / `--chat-fs-*` with literals like `control: 13.5px`,
`page-title: 24px`) that drifted from the rem scale. These aliases now point
at the canonical `--fs-*` vars in `conversations/inbox/tokens.css`, so there
is one scale. Callers that still write `var(--crm-fs-control)` keep working
unchanged and now resolve to the same value as `text-control`.

## Drift prevention

A check script at `scripts/check-typography.mjs` scans for arbitrary font-size
values and reports violations. Run it locally or wire it into CI:

```bash
node scripts/check-typography.mjs
```

Exits non-zero if any raw Tailwind size, `text-[<number>]`, numeric inline
`fontSize`, or out-of-scale component `font-size:` is found. Only the central
token owners (`index.css`, `tokens.css`) and documented branding motifs may
define fixed values.
