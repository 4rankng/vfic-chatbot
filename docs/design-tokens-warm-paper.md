# Design Tokens — Warm-Paper Workspace

> **Status:** Active — supersedes the cool-neutral `.workspace-frame` palette.
> **Scope:** All logged-in recruiter/admin workspaces. Login, Forgot-Password,
> and Knowledge pages already use this palette via `.kb-scope` and are unchanged.
> **Dark workspace:** Out of scope. `.workspace-frame` forces a light palette
> regardless of the system `.dark` class (see
> [Non-goals](#out-of-scope)).
>
> Source of truth: `frontend/src/index.css` (`--workspace-*`, `:root`,
> `.workspace-frame`) and `frontend/src/components/atomic-crm/conversations/inbox/tokens.css`.

## Direction

A calm, editorial, enterprise-grade **paper-and-ink** workspace — beige/paper
canvas, pure-white elevated surfaces, deep-ink primary actions, and a single
restrained teal accent for selection, links, and focus. Premium feel comes from
warmth and typographic hierarchy, not from a dark shell or saturated color.

| Role | Color | Hex |
|---|---|---|
| Canvas (page bg) | Paper | `#f5f6f1` |
| Elevated surface | White | `#ffffff` |
| Muted surface | Paper-deep | `#eceee5` |
| Primary action (filled buttons, selected nav) | Ink-900 | `#15201c` |
| Body text | Ink-900 | `#15201c` |
| Secondary text | Ink-500 | `#5c6760` |
| Selection tint / links / focus | Teal | `#1f6f54` |
| Selection soft background | Teal-soft | `#e3f0ea` |
| Border / hairline | Line | `#dee2d8` |
| Warning | Ochre | `#8a5a14` |
| Danger / destructive | Rust | `#b23a2e` |

**Decision:** Ink carries the **primary action**; teal is reserved for
**selection, links, focus, and healthy/active signals**. This keeps the interface
editorial and mature, avoids the "pale green everywhere" problem, and lets teal
communicate *meaning* (selected, active, healthy) rather than decoration.

## Token table (light)

### Workspace namespace (`--workspace-*` in `index.css :root`)

These are the source-of-truth primitives. `.workspace-frame` re-maps the standard
shadcn semantic tokens (`--background`, `--primary`, …) onto these values.

| Token | Value | Purpose |
|---|---|---|
| `--workspace-canvas` | `#f5f6f1` | Page background (paper) |
| `--workspace-surface` | `#ffffff` | Elevated cards/content |
| `--workspace-surface-muted` | `#eceee5` | Secondary surface, hover |
| `--workspace-ink` | `#15201c` | Primary text, ink-900 |
| `--workspace-ink-muted` | `#5c6760` | Secondary text, ink-500 |
| `--workspace-border` | `#dee2d8` | Hairline |
| `--workspace-focus` | `#1f6f54` | Focus ring (teal) |
| `--workspace-action` | `#15201c` | Primary action fill (ink) |
| `--workspace-action-strong` | `#0d1714` | Ink-950 (pressed/strong) |
| `--workspace-success` | `#1f6f54` | Success/healthy (teal) |
| `--workspace-warning` | `#8a5a14` | Warning (ochre) |
| `--workspace-danger` | `#b23a2e` | Destructive (rust) |

### Workspace accent tokens

| Token | Value | Purpose |
|---|---|---|
| `--workspace-teal` | `#1f6f54` | Teal accent |
| `--workspace-teal-soft` | `#e3f0ea` | Selection tint background |
| `--workspace-paper` | `#f5f6f1` | Paper alias |
| `--workspace-paper-deep` | `#eceee5` | Paper-deep alias |

### Standard shadcn semantic tokens (`:root`)

| Token | Value | Notes |
|---|---|---|
| `--background` | `#f5f6f1` | paper |
| `--foreground` | `#15201c` | ink-900 |
| `--card` | `#ffffff` | elevated white |
| `--card-foreground` | `#15201c` | |
| `--popover` | `#ffffff` | |
| `--popover-foreground` | `#15201c` | |
| `--primary` | `#15201c` | **ink = primary action** |
| `--primary-foreground` | `#f5f6f1` | paper text on ink |
| `--secondary` | `#eceee5` | paper-deep |
| `--secondary-foreground` | `#15201c` | |
| `--muted` | `#eceee5` | |
| `--muted-foreground` | `#5c6760` | ink-500 |
| `--accent` | `#e3f0ea` | teal-soft (selection) |
| `--accent-foreground` | `#1f6f54` | teal |
| `--destructive` | `#b23a2e` | rust |
| `--destructive-foreground` | `#ffffff` | |
| `--border` | `#dee2d8` | line |
| `--input` | `#dee2d8` | |
| `--ring` | `#1f6f54` | teal focus |
| `--radius` | `10px` | unchanged |

### Chart tokens (`:root`)

| Token | Value | Purpose |
|---|---|---|
| `--chart-1` | `#5c6760` | ink-500 (default bars) |
| `--chart-2` | `#1f6f54` | teal |
| `--chart-3` | `#b54708` | rust |
| `--chart-4` | `#8a5a14` | ochre |
| `--chart-5` | `#9ca59c` | ink-300 |

> Performance `.performance-bar i.is-llm` uses explicit teal (`#1f6f54`) rather
> than `var(--primary)` (now ink) so the LLM bottleneck stays a healthy teal.

### Lead-priority tokens (`:root`)

| Token | Value | Purpose |
|---|---|---|
| `--lead-hot-bg` | `#f8e7e4` | rust-soft |
| `--lead-hot-ink` | `#9c2f24` | rust-strong |
| `--lead-warm-bg` | `#f4ecda` | ochre-soft |
| `--lead-warm-ink` | `#8a5a14` | ochre |
| `--lead-cold-bg` | `color-mix(in oklab, var(--muted-foreground) 14%, var(--background))` | neutral |
| `--lead-cold-ink` | `#5c6760` | ink-500 |

### Inbox mirror tokens (`conversations/inbox/tokens.css`)

The inbox carries a local mirror of brand/success/chat-bubble/workspace tokens.
After migration it tracks the warm-paper palette:

| Token | Value | Notes |
|---|---|---|
| `--primary-soft` | `#e3f0ea` | teal-soft |
| `--primary-soft-border` | `#cce5df` | |
| `--inbox-accent` / `--brand` | `var(--color-teal, #1f6f54)` | **teal** — inbox accent identity (~120 call-sites) |
| `--brand-hover` | `#1a5f48` | teal hover (for gradients) |
| `--brand-light` | `#e3f0ea` | teal-soft |
| `--success` | `var(--color-green, #1f6f54)` | teal |
| `--success-light` | `#e3f0ea` | |
| `--chat-bg` | `#f5f6f1` | paper |
| `--chat-bubble-user` | `#ffffff` | candidate (neutral white) |
| `--chat-bubble-bot` | `#e3f0ea` | teal-soft (outgoing) |
| `--chat-bubble-agent` | `#e3f0ea` | teal-soft (outgoing) |
| `--workspace-bg` | `#ffffff` | |
| `--workspace-bg-deep` | `#f5f6f1` | paper |
| `--workspace-ink` | `#15201c` | |
| `--workspace-muted` | `#5c6760` | |
| `--workspace-faint` | `#646e63` | AA-compliant faint text (4.89:1 on paper) |
| `--workspace-hover` | `#eceee5` | paper-deep |

## Chat bubble roles

| Sender | Background | Identity |
|---|---|---|
| Candidate (inbound `.user`) | `#ffffff` white | neutral — the applicant |
| Bot (outgoing) | `#e3f0ea` teal-soft | automated reply |
| Agent/recruiter (outgoing) | `#e3f0ea` teal-soft | human takeover |
| System event | `var(--surface-hover)` | muted |

> Teal-soft bubbles preserve the "outgoing = teal" semantic on the new warm
> paper canvas. Candidate stays neutral white to keep inbound/outbound contrast
> clear without saturated green.

## Before → After (key tokens)

| Token | Before (cool) | After (warm-paper) |
|---|---|---|
| `--workspace-canvas` | `#f7f8fa` | `#f5f6f1` |
| `--workspace-surface` | `#fcfcfd` | `#ffffff` |
| `--workspace-surface-muted` | `#f2f4f7` | `#eceee5` |
| `--workspace-ink` | `#17212b` | `#15201c` |
| `--workspace-ink-muted` | `#475467` | `#5c6760` |
| `--workspace-border` | `#e4e7ec` | `#dee2d8` |
| `--workspace-action` | `#087a5b` (teal) | `#15201c` (ink) |
| `--workspace-success` | `#087a5b` | `#1f6f54` |
| `--primary` (workspace) | `#087a5b` (teal) | `#15201c` (ink) |
| `--accent` (workspace) | `#e8f5f0` | `#e3f0ea` |
| `--ring` (workspace) | `#087a5b` | `#1f6f54` |

## Contrast (WCAG 2.2 AA)

| Combination | Ratio | Pass |
|---|---|---|
| Ink `#15201c` on Paper `#f5f6f1` | ~14.2:1 | AAA |
| Ink-500 `#5c6760` on Paper `#f5f6f1` | ~5.3:1 | AA |
| Faint `#646e63` on Paper `#f5f6f1` | ~4.9:1 | AA |
| Faint `#646e63` on White `#ffffff` | ~5.3:1 | AA |
| Ink-300 `#9ca59c` on Paper | ~2.6:1 | large/UI only |
| Paper `#f5f6f1` on Ink `#15201c` (primary btn) | ~14.2:1 | AAA |
| Teal `#1f6f54` on Teal-soft `#e3f0ea` (accent-fg) | ~5.8:1 | AA |
| Rust `#9c2f24` on Rust-soft `#f8e7e4` (lead-hot) | ~5.4:1 | AA |

> Muted-foreground (`#5c6760`) and faint (`#646e63`) are the AA-compliant tiers
> for secondary/metadata text (timestamps, placeholders, hints). Reserve
> `#9ca59c` (ink-300) for non-text decorative borders and dividers only.

## Semantic emphasis rules (ink-as-primary implications)

Because **global `--primary` is now ink** (not teal), a few components use **teal
explicitly** rather than `var(--primary)` to preserve their signal:

1. **Navigation active state** — teal-soft background (`#e3f0ea`) + teal-strong
   text. Teal = "you are here".
2. **Performance LLM bar** (`.performance-bar i.is-llm`) — explicit teal
   (`#1f6f54`), not `var(--primary)`. The bottleneck stays a healthy teal.
3. **Links** — teal `#1f6f54` (accent-foreground), not ink.
4. **Inbox filled controls use teal, not ink.** The inbox's `--brand` token
   resolves to **teal** (`var(--color-teal)`), deliberately distinct from the
   global ink `--primary`. So inbox controls that fill with `var(--brand)` —
   the send button, header-avatar gradient, conversation active left-accent,
   context-drawer action buttons — render **teal**, preserving the inbox's
   accent identity. This is an intentional divergence: global shadcn
   `<Button variant="default">` (uses `--primary`) = ink; inbox action controls
   (use `--brand`) = teal. Reconciling them is a deferred follow-up.

## Out of scope

- Dark-workspace redesign (`.workspace-frame` forces light).
- Backend / DB / API / payload / auth / RBAC / route changes.
- New chart library, component library, state manager, or feature flag.
- Login / Forgot-Password redesign (already `.kb-scope` = target palette).
- Replacing/sanitizing malformed `U+FFFD` message data (upstream follow-up).

## References

- `frontend/src/index.css` — `:root`, `.workspace-frame`, `@theme inline`.
- `frontend/src/components/atomic-crm/conversations/inbox/tokens.css` — inbox mirror.
- `frontend/src/components/atomic-crm/performance/performance.css` — uses global tokens only.
- Superseded plan: `plans/260710-1322-frontend-ui-ux-redesign/` (architecture,
  contracts, responsive, a11y phases remain the source of truth for those concerns;
  only its palette values are superseded by this document).
