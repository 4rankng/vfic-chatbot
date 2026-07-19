# Design Tokens — Ting Ting Recruiting Control Room

The authenticated recruiter console uses a custom daisyUI v5 theme as its
visual foundation. `frontend/src/index.css` owns the light-only `tingting`
theme and maps it onto the stable `--workspace-*` roles used by feature styles.
Inbox aliases and typography remain in
`conversations/inbox/tokens.css`.

The theme provider always removes stale `.dark` state, applies `.light`, and
sets `data-theme="tingting"`. Stored preferences and OS color-scheme settings do
not alter the recruiter console. Feature components must not introduce
independent theme state or a theme toggle.

## Theme roles

| Product role | daisyUI role | Compatibility token |
|---|---|---|
| Main content surface | `base-100` | `--workspace-surface` |
| Cloud canvas | `base-200` | `--workspace-canvas` |
| Muted/selected surface | `base-300`, `accent` | `--workspace-surface-muted`, `--workspace-teal-soft` |
| Primary text | `base-content` | `--workspace-ink` |
| Navigation shell | `secondary` | `--workspace-shell` |
| Primary action and focus | `primary` | `--workspace-action`, `--workspace-focus` |
| Success | `success` | `--workspace-success` |
| Warning | `warning` | `--workspace-warning` |
| Error | `error` | `--workspace-danger` |

The console uses cool cloud surfaces, deep denim navigation, and one restrained
steel-blue action accent. Color is never the only status cue: labels or icons accompany
selection, warning, delivery, and intervention states.

## Component contract

- daisyUI classes use the `tt-` prefix. Never use unprefixed generic classes
  such as `btn`, `card`, `menu`, `chat`, or `input`.
- Use daisyUI for presentational anatomy such as buttons, badges, alerts,
  skeletons, avatars, chat bubbles, forms, tables, pagination, collapsible
  settings, and simple surface groups.
- Shared primitives under `frontend/src/components/ui/` are the migration
  boundary. Buttons, inputs, textareas, badges, alerts, cards, breadcrumbs,
  pagination, selections, tables, tabs, dialogs, checkboxes, radios, toggles,
  loading states, and skeletons expose prefixed daisyUI anatomy so every admin
  resource inherits the same system.
- Keep Radix/Shadcn as the behavior owner for dialogs, sheets, selects,
  dropdowns, checkboxes, radios, toggles, and other focus-managed controls;
  daisyUI owns their visual anatomy without replacing focus management or
  keyboard behavior.
- The plugin `include` list contains only component families present in
  production markup. MCP references may cover more families during design,
  but unused CSS must not enter the bundle.
- Avoid wrapper elements inside virtualized rows. Add presentational classes to
  stable existing nodes so scroll measurement and anchoring remain unchanged.
- Text action buttons follow a 28/32/36px small/normal/large desktop scale with
  13px labels. Desktop icon controls are 32/36px, while every mobile touch
  target remains at least 44px. Mobile inputs remain 16px to prevent browser
  focus zoom.
- Be Vietnam Pro is the console typeface at weights 400, 500, 600, and 700.
  Body/list text is at least 14px on mobile; metadata is at least 12px.

The dashboard and ordinary secondary workspaces use document scrolling on
mobile. Conversation detail is intentionally different: the transcript remains
the single virtualized overflow owner and the composer remains a stable footer
boundary. Do not convert the transcript to document scroll or add another
nested scrolling region.

The login and password-recovery entry points use the shared light-only daisyUI
hero/card shell, the Ting Ting logo lockup, and the project-owned
`login-recruiting-console-v2.webp` illustration. Desktop keeps the artwork and
form in a balanced split view; mobile crops the same visual into a compact
banner above the form. Authentication copy stays intentionally brief and must
not expose installation-state language such as “Thiết lập hệ thống”.
