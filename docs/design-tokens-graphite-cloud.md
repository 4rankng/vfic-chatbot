# Design Tokens — Graphite, Cloud, and Emerald

The authenticated operations workspace uses these semantic roles. The source
of truth is `frontend/src/index.css`; inbox aliases consume the same roles in
`conversations/inbox/tokens.css`.

| Role | Token | Value |
|---|---|---|
| Application shell | `--workspace-navigation` | `#0F172A` |
| Shell hover | `--workspace-surface-muted` | `#172033` (navigation context) |
| Main canvas | `--workspace-canvas` | `#EEF2F6` |
| Secondary canvas | `--workspace-surface-muted` | `#F4F6F8` |
| Primary surface | `--workspace-surface` | `#FAFBFC` |
| Elevated surface | `--settings-elevated` | `#FFFFFF` |
| Selected surface | `--workspace-teal-soft` | `#DFF3EC` |
| Primary text | `--workspace-ink` | `#111827` |
| Secondary text | `--workspace-ink-muted` | `#475569` |
| Border | `--workspace-border` | `#D4DCE6` |
| Brand/focus | `--workspace-action`, `--workspace-focus` | `#0F8A68` |
| Brand pressed | `--workspace-action-strong` | `#095B48` |
| Success | `--workspace-success` | `#16835D` |
| Warning | `--workspace-warning` | `#B7791F` |
| Error | `--workspace-danger` | `#C2414B` |

Use the shell only for global navigation. Use elevated white sparingly for
cards and inputs; content canvases stay cool-neutral. Emerald communicates
selection, focus, primary actions, and healthy status—not generic decoration.
