# Design Tokens — Ting Ting Console Blue

The authenticated operations workspace uses these semantic roles.
`frontend/src/index.css` owns the shared `--workspace-*` roles; inbox aliases
and typography live in `conversations/inbox/tokens.css`. Settings and
performance may define feature-scoped aliases when a component needs a local
surface role.

| Role | Token | Value |
|---|---|---|
| Application shell | `--workspace-shell` | `#506EAE` |
| Shell active | `--workspace-shell-active` | `#394F79` |
| Rail active | `--workspace-rail-active` | `#304062` |
| Main canvas | `--workspace-canvas` | `#F1F3F6` |
| Conversation canvas | `--chat-bg` (inbox scope) | `#E4DFD8` |
| Secondary surface | `--workspace-surface-muted` | `#EAECF0` |
| Primary surface | `--workspace-surface` | `#FFFFFF` |
| Elevated settings surface | `--settings-elevated` (settings scope) | `#FFFFFF` |
| Selected surface | `--workspace-teal-soft` | `#E4EFFF` |
| Outgoing message | `--bubble-agent-bg`, `--bubble-bot-bg` | `#DCF8C7` |
| Primary text | `--workspace-ink` | `#344054` |
| Secondary text | `--workspace-ink-muted` | `#667085` |
| Border | `--workspace-border` | `#D8DDE6` |
| Brand/focus | `--workspace-action`, `--workspace-focus` | `#1777FF` |
| Active text | `--workspace-teal-strong` | `#0267E8` |
| Brand pressed | `--workspace-action-strong` | `#0267E8` |
| Success | `--workspace-success` | `#16835D` |
| Warning | `--workspace-warning` | `#B7791F` |
| Error | `--workspace-danger` | `#C2414B` |

Use console blue for the global topbar, icon rail, focus, selection, and primary
actions. Keep the conversation queue and information panel white, and reserve
the warm neutral canvas for message history. Green outgoing bubbles indicate
messages sent by Ting Ting Soft; green is not a global brand color.
