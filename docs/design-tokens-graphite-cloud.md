# Design Tokens — Graphite, Cloud, and Emerald

The authenticated operations workspace uses these semantic roles.
`frontend/src/index.css` owns the shared `--workspace-*` roles; inbox aliases
and typography live in `conversations/inbox/tokens.css`. Settings and
performance may define feature-scoped aliases when a component needs a local
surface role.

| Role | Token | Value |
|---|---|---|
| Application shell | Desktop navigation selector | `#0F172A` |
| Shell hover | Desktop navigation selector | `#172033` |
| Main canvas | `--workspace-canvas` | `#EEF2F6` |
| Secondary canvas | `--workspace-surface-muted` | `#F4F6F8` |
| Primary surface | `--workspace-surface` | `#FAFBFC` |
| Elevated settings surface | `--settings-elevated` (settings scope) | `#FFFFFF` |
| Selected surface | `--workspace-teal-soft` | `#DFF3EC` |
| Primary text | `--workspace-ink` | `#111827` |
| Secondary text | `--workspace-ink-muted` | `#475569` |
| Border | `--workspace-border` | `#D4DCE6` |
| Brand/focus | `--workspace-action`, `--workspace-focus` | `#0F8A68` |
| Active text on mint | `--workspace-teal-strong` | `#08765A` |
| Brand pressed | `--workspace-action-strong` | `#095B48` |
| Success | `--workspace-success` | `#16835D` |
| Warning | `--workspace-warning` | `#B7791F` |
| Error | `--workspace-danger` | `#C2414B` |

Use the shell only for global navigation. Use elevated white sparingly for
cards and inputs; content canvases stay cool-neutral. Emerald communicates
selection, focus, primary actions, and healthy status—not generic decoration.
