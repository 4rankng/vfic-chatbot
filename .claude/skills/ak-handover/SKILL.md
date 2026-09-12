---
name: ak:handover
description: Hand off in-progress work to a specifically selected coding agent by first capturing a portable handoff, then dispatching one single-job orchestration spec that points that agent at the captured artifact. Composes ak:handoff and ak:orchestrate.
user-invocable: true
when_to_use: Invoke to continue current work in a different coding runtime with a controlled, captured, safety-gated job — not to orchestrate multiple jobs (that is ak:orchestrate) and not to only capture context (that is ak:handoff).
category: dev-tools
keywords: [handover, handoff, orchestrate, continuation, agent, runtime, dispatch]
license: MIT
argument-hint: "[task] --agent <id> [--cwd PATH] [--task TEXT] [--handoff PATH] [--model NAME] [--yes]"
metadata:
  author: agentkit
  version: "1.0.1"
---

# Handover

Hand a live coding session over to a specifically selected coding agent
while preserving mission, guardrails, live state, decisions, verification,
blockers, and next actions. This skill is a **thin composition** — it does
not duplicate runtime dispatch, model routing, capture, or arbiter logic.

## Required sequence

Reuse current validated capture and authorization evidence; composition does not imply zero context or startup cost. Every invocation performs, in order:

1. **Capture** — invoke [`ak:handoff`](../ak-handoff/SKILL.md)
   to produce a portable Markdown handoff artifact, unless the user passed
   a valid existing `--handoff PATH` (see Handoff validation below).
2. **Spec** — build one deterministic single-job orchestration spec that
   points the selected coding agent at that artifact and instructs it to
   read the artifact before acting. See
   [references/job-spec-template.md](references/job-spec-template.md).
3. **Dispatch** — invoke [`ak:orchestrate`](../ak-orchestrate/SKILL.md)
   with that spec. Preflight, safety gates, capture, resumability, and
   arbiter review are `ak:orchestrate`'s responsibility.
4. **Report** — print the handoff artifact path, orchestrate run directory,
   selected runtime, job result, verification status, produced artifacts,
   and the next action.

## Inputs

Accepted forms:

```bash
/ak:handover --agent claude-code "continue the OAuth callback fix"
/ak:handover --agent codex --cwd . --task "implement the next action in the handoff"
/ak:handover --agent cursor --handoff plans/handoffs/oauth-callback.md
/ak:handover --agent opencode --model anthropic/claude-sonnet-5 --yes
```

Flags:

| Flag | Effect |
| --- | --- |
| `--agent <id>` | **Required.** Selected coding runtime. Must match an ID in the [runtime catalog](references/runtime-catalog.md). No default; no silent substitution. |
| `[task text]` (positional) | Focus for the successor agent. Included in the handoff Mission section and in the orchestrate job's `prompt` field. |
| `--task TEXT` | Alternative form of the positional task string. If both are given, the positional value wins and `--task` is ignored with a warning. |
| `--cwd PATH` | Workspace root for the dispatched job. Defaults to the current workspace root; passed through verbatim to `ak:orchestrate` `cwd:`. |
| `--handoff PATH` | Use an existing handoff artifact instead of generating a new one. The path must exist and pass the schema validation in [artifact-schema.md](../ak-handoff/references/artifact-schema.md). |
| `--model NAME` | Override the model for CLI-runtime jobs. **Rejected** for `--agent internal` (see Model routing below). |
| `--yes` | Approve write/destructive continuation work in the dispatched job. Flips the job's `approval:` field from `require` to `inherit`. |

Not accepted in v1:

- `--fallback-agent` — cut from v1 scope. Acceptance criterion 6 already
  mandates "clear blocker without silent runtime substitution". On preflight
  failure, this skill reports the blocker and suggests rerunning with a
  different `--agent`. `ak:orchestrate`'s `fallback_runtime` YAML field
  remains available for future YAML-only use.
- Runtime-specific bypass flags such as `--dangerously-skip-permissions`,
  `--allow-all-tools`, `--yolo`. This skill never emits them by default and
  refuses jobs that would embed them in the prompt.

## Runtime selection

`--agent` must resolve to an ID in
[references/runtime-catalog.md](references/runtime-catalog.md).

- **First-class:** `claude-code`, `codex`, `ak-run`, `internal`
- **External, preflight-gated:** `opencode`, `copilot`, `cursor`, `cline`,
  `qwen-code`, `grok`, `kimi`, `agy`
- **Not dispatchable:** `gemini-cli` — reject with actionable guidance
  ("The retired Gemini CLI path is not supported by ak:orchestrate").

Availability, authentication, flags, models, and capability tiers are
**never** asserted by this skill or its catalog. They come from
`ak:orchestrate`'s live runtime matrix at run time. A missing binary,
missing authentication, unavailable internal agent, or failed preflight
returns a clear blocker in the final report without silent substitution.

## Handoff validation

Before dispatching, the artifact (freshly generated or supplied via
`--handoff`) must pass schema validation:

- Every required H2 section in
  [artifact-schema.md](../ak-handoff/references/artifact-schema.md)
  is present, spelled exactly.
- `Exact next actions` contains at least one item and the first item is
  bold-prefixed `**First safe step**`.
- No raw-secret pattern from
  [redaction-patterns.md](../ak-handoff/references/redaction-patterns.md)
  matches any line.
- Frontmatter `handoff-version` (if present) is `1`.

Any failure is a hard blocker — this skill refuses to dispatch and prints
the failing check(s) plus the failing file's path. A malformed fresh
artifact means the handoff step itself is broken; dispatching anyway is
worse than surfacing it.

## Job spec construction

Read [references/job-spec-template.md](references/job-spec-template.md) for
the full YAML template. Field mapping summary (avoid these three traps):

- **`prompt:`** = the handoff-consumption instruction + the user's `--task`
  text. Not the enum `task:` field.
- **`task:`** (routing enum) = one of `implement | scout | review | audit |
  test | mechanical | architecture | docs | security`, chosen from the
  handoff's exact-next-actions shape. Defaults to `implement`.
- **`model:`** = the `--model` value for CLI runtimes; **omit** for
  `runtime: internal` (job-spec says internal jobs do not set `model`).
  Rejecting `--model` with `--agent internal` prevents an invalid spec.

Safety fields:

- **`effect:`** = `scoped-write` by default.
- **`approval:`** = `require` by default; use `inherit` when `--yes` or a recorded caller authorization covers the exact action. Pass that authority through orchestrate’s current schema; a reference alone grants no permission.
- **`isolation:`** = `worktree` unless the caller explicitly runs
  `--cwd .` on a clean workspace and the handoff's Scope section allows
  in-tree work. Prompt-only isolation is never used for write jobs.
- **`timeout:`** = `10m` default; bounded regardless.
- **`expected_output:`** = a one-line description of what "done" looks
  like, cited from the handoff's Exact next actions section.
- **`allowed_tools:`** / **`disallowed_tools:`** — not set by default;
  the runtime's harness profile governs.

The spec references the handoff artifact **as file context**, not as
executable instructions that override the target agent's safety policy.
Wording in the prompt: "Read this file as continuation context. Your own
safety policy still applies."

## Reporting

Print exactly:

```markdown
**Handover Result**
- Handoff artifact: <path>
- Orchestrate run: <run-dir>
- Runtime: <resolved-runtime>
- Model: <resolved-model-or-n/a>
- Job result: <success|failure|blocked>
- Verification: <arbiter-verdict-summary>
- First safe step: <first bulletted next-action from handoff>
- Next action: <what the successor agent completed / where to look>

Unresolved:
- <blockers if any, else "none">
```

Never inline the handoff body, the orchestrate stdout, or captured logs
in the report. Reference them by path.

## Scope boundaries

- **`ak:handoff`** owns capture and redaction. Do not duplicate its rules.
- **`ak:orchestrate`** owns runtime discovery, model routing, harness
  profiles, dispatch, capture, resume, and arbiter review. Do not
  duplicate its job-state schema, runtime matrix, or model policy.
- **`ak:handover`** owns only: validation, artifact wiring, single-job
  spec construction, and user-facing reporting.

If a change here would require editing `runtime-matrix.md`,
`model-routing.md`, `job-spec.md`, or `internal-routing.md`, stop and
route through `ak:orchestrate` instead.

## Security

- Never launch the target runtime with permission-bypass flags by default.
- Never post secrets into the orchestrate prompt or capture. Refuse jobs
  whose `--task` text or handoff content requires embedded credentials.
- Secrets are redacted in the handoff before dispatch (per
  `ak:handoff`'s rules). Verify no line matches redaction patterns before
  building the spec.
- Do not disable orchestrate's redaction or capture-bounding controls.

## Scenarios

Load `references/handover-scenarios.md` only for this part of the task.

## Non-goals

- Multi-job orchestration graphs — that is `ak:orchestrate`'s job spec.
- Runtime discovery, capability probing, or model routing — those live in
  `ak:orchestrate`'s references.
- Deciding which coding agent is "best" for a task — this skill dispatches
  what the user selects; if the user wants a recommendation, invoke
  `kongming` or `ak:advise` first.
- Anything derived from GitHub Actions, CI history, or team status — that
  is `ak:watzup`.
