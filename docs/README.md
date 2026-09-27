# Documentation

Reference documentation for TingHire — the Vietnamese recruiting chatbot and
recruiter console (production at `bot.tingting.vip`). Plans live in `../plans/`,
dated work records in `journals/`; this tree holds the current reference docs
and is kept true to the code.

## Layout

| Directory | What belongs here |
|---|---|
| `product/` | What the product is and where it is going: PDR, roadmap, codebase summary |
| `architecture/` | How the system is built: runtime architecture, database, API reference, agent/ADK layering |
| `development/` | How to work on the repo: code standards and the testing strategy |
| `ops/` | How to run and operate production: deployment, incidents, QA, droplet backup/restore |
| `design/` | The UI design system: design QA, design tokens, typography |
| `guides/` | Channel and feature how-tos: Messenger onboarding, knowledge-base workflow |
| `decisions/` | Architecture decision records (ADRs) — why the stack is what it is |
| `journals/` | Dated work records and post-mortems; never pruned |
| `research/` | Point-in-time technical research |
| `troubleshooting/` | The chatbot response-path debugging map and its index |
| `archive/` | Superseded or dated artifacts kept for history: the July HLD draft, the latency plan, early brainstorms |

## Start here

- New to the repo: `product/overview-pdr.md`, then `architecture/system-architecture.md`
- Before touching code: `development/code-standards.md` (incl. gate notes) and `development/testing.md`
- Deploying or on-call: `ops/deployment-guide.md`, `ops/incident-runbook.md`
- Debugging the bot pipeline: `troubleshooting/README.md`
- Why is it built this way: `decisions/README.md`

## Conventions

- One topic per file, kebab-case filenames (`droplet-backup-restore.md`, not `DROPLET-BACKUP-RESTORE.md`).
- Evergreen docs live in the topic directories above; dated explorations move to `archive/` once superseded; per-change records go to `../plans/reports/` and `journals/`.
- Relative links between docs are kept resolving — update them when files move.
- `ops/deployment-guide.md` is load-bearing: the root `Makefile` release gate greps it for the current Alembic HEAD, so keep its `**HEAD:**` line current when you add migrations.
