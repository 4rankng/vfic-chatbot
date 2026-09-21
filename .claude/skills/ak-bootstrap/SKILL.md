---
name: ak:bootstrap
description: "Bootstrap new projects with research, tech stack, design, planning, and implementation. Modes: full (default thorough), auto (explicit autonomous), fast (skip research), parallel (multi-agent)."
user-invocable: true
when_to_use: "Invoke to start a new project or full-stack setup from scratch."
category: workflow
keywords: [scaffold, project, setup, boilerplate]
license: MIT
argument-hint: "[requirements] [--full|--auto|--fast|--parallel] [--ultra] [--yagni] [--skip-journal]"
metadata:
  author: agentkit
  version: "1.1.3"
---

# Bootstrap - New Project Scaffolding

End-to-end project bootstrapping from idea to running code.

**Principles:** KISS, DRY | Full requested scope, nothing extra (`--yagni` to opt into scope-cutting) | Token efficiency | Concise reports

## Usage

```
/ak:bootstrap <user-requirements>
```

**Flags** (optional, default `--full`):

| Flag | Mode | User Gates | Planning Skill | Cook Skill |
|------|------|------------|----------------|------------|
| `--full` | Full workflow | Missing material decisions | `--hard` | default continuation |
| `--auto` | Automatic explicit opt-in | Missing material decisions | `--auto` | `--auto` |
| `--fast` | Quick | Missing material decisions | `--fast` | default continuation |
| `--parallel` | Multi-agent | Missing material decisions | `--parallel` | `--parallel` |

**Composable flags** (combine with any mode):

| Flag | Effect |
|------|--------|
| `--yagni` | Opt into YAGNI: challenge and cut scope not needed for the stated outcome (default: scaffold the full requested scope). Passed through to `ak:plan` and `ak:cook` |
| `--ultra` | Planning uses the best-of-5 verifier mode: the planning phase runs `/ak:plan --ultra` instead of the mode-mapped plan flag (see Ultra Verifier Mode). Hard-conflicts with `--parallel` |

**Example:**
```
/ak:bootstrap "Build a SaaS dashboard with auth" --fast
/ak:bootstrap "E-commerce platform with Stripe" --parallel
```

## Opening brainstorm gate (all modes)

Before Git initialization, research, design, planning, or scaffolding, capture:

- the intended product outcome;
- technology, safety, compatibility, and delivery constraints;
- explicit non-goals for this bootstrap;
- observable acceptance criteria for the running project.

Reuse an accepted brief or plan when it already contains these fields. Ask only
about a missing decision that would materially change the product or safety.
`--fast`, `--parallel`, and explicit `--auto` do not skip this gate; they only
change execution and approval behavior after the contract is concrete.

## Workflow Overview

```
[Brainstorm Contract] → [Git Init] → [Research?] → [Tech Stack?] → [Design?] → [Planning] → [Implementation] → [Test] → [Review] → [Docs] → [Onboard] → [Final]
```

Each mode loads a specific workflow reference + shared phases.

## Mode Detection

If no flag provided, default to `--full`.

Load the appropriate workflow reference:
- `--full`: Load `references/workflow-full.md`
- `--auto`: Load `references/workflow-auto.md` only when explicitly requested
- `--fast`: Load `references/workflow-fast.md`
- `--parallel`: Load `references/workflow-parallel.md`

All mode references inherit the opening brainstorm contract. Load
`references/shared-phases.md` for implementation through final report.

## Step 0: Git Init (ALL modes)

Inspect the actual destination, existing files, manifests and Git state first. Reuse an existing project and its branch conventions; never re-scaffold or reset it. Initialize Git only for a new project when included in the requested setup, using the repository’s requested/default branch. Preserve unrelated files.

## Downstream ownership

After early phases (research, tech stack, design), trigger downstream skills:

### Planning Phase
Activate **ak:plan** skill with mode-appropriate flag:
- `--full` → `/ak:plan --hard <requirements>` (thorough research + validation)
- `--auto` → `/ak:plan --auto <requirements>` (auto-detect complexity)
- `--fast` → `/ak:plan --fast <requirements>` (skip research)
- `--parallel` → `/ak:plan --parallel <requirements>` (file ownership + dependency graph)

Under `--ultra`, substitute `/ak:plan --ultra <requirements>` for the mode-mapped
flag above (see Ultra Verifier Mode); this override also applies inside the
loaded workflow references. With `--parallel`, the combination is a hard-stop.

Pass the brainstorm contract with the requirements so planning preserves the
accepted outcome, constraints, non-goals, and acceptance criteria.

Planning skill outputs a plan path. Pass this to cook.

### Implementation Phase
Activate **ak:cook** skill with the plan path and mode-appropriate flag:
- `--full` → `/ak:cook <plan-path>` (continue within accepted scope)
- `--auto` → `/ak:cook --auto <plan-path>` (explicit autonomous implementation)
- `--fast` → `/ak:cook <plan-path>` (skip extra research, continue within accepted scope)
- `--parallel` → `/ak:cook --parallel <plan-path>` (multi-agent execution)

## Role

Elite software engineering expert specializing in system architecture and technical decisions. Brutally honest about feasibility and trade-offs.

## Critical Rules

- Activate relevant skills from catalog during the process
- Keep all research reports ≤150 lines
- Resolve documentation paths from repository instructions and navigation
- Plans written to `./plans` directory using naming from `## Naming` section
- DO NOT implement code directly — delegate through planning + cook skills
- Lead with the outcome. Keep reports short by being selective, not by compressing the writing into fragments or arrow chains; write complete sentences.
- List unresolved questions at end of reports
- Follow the installed journal owner and its opt-out preference to write a concise technical journal entry upon completion — unless the shared "Journal step — opt-out" below applies.

### Journal step — opt-out

Skip the automatic `/ak:journal` step when either applies:
- The invocation includes the `--skip-journal` flag, OR
- `ak config prefs resolve --json | jq -r 'if .prefs.journal.auto == false then "false" else "true" end'` returns `false`. If the command errors or prints anything other than the exact string `false`, treat as `true` (default) — corrupt or missing config never suppresses the automatic journal.

Precedence: flag > project config > user config > default (`true`).
When skipped, print one line:
- `journal skipped by --skip-journal` (flag), or
- `journal skipped by preference` (config).

Explicit `/ak:journal` and `ak journal create` are unaffected.

## References

- `references/workflow-full.md` - Full interactive workflow
- `references/workflow-auto.md` - Explicit auto workflow
- `references/workflow-fast.md` - Fast workflow
- `references/workflow-parallel.md` - Parallel workflow
- `references/shared-phases.md` - Common phases (implementation → final report)

## Ultra Verifier Mode (`--ultra`)

Bootstrap does not fan itself. When `--ultra` is present, the planning phase
runs `/ak:plan --ultra` instead of the mode-mapped plan flag (`--hard`,
`--auto`, `--fast`) — plan's `--ultra` is exclusive with those mode flags, and
the plan skill owns the best-of-5 candidate dispatch, verification, and
winner-selection finalizer. Cook still runs with the mode-appropriate flag.

`--ultra` hard-conflicts with `--parallel`: plan `--parallel` produces the
file-ownership and dependency-graph structure that cook `--parallel` consumes,
and a single winning ultra plan does not carry it. On that combination,
hard-stop and ask the user to drop one flag; never resolve it silently.

Full mechanics live in `../ak-brainstorm/references/ultra-verifier-mode.md`. It
is a best-of-5 verifier mode inspired by LLM-as-a-Verifier, not the full
framework.
