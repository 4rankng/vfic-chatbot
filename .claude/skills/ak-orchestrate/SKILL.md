---
name: ak:orchestrate
description: "Coordinate staged or parallel jobs across live-verified coding-agent runtimes and in-session subagents, using capability- and risk-based routing, worktree-isolated writes, resumable state, capture, safety gates, and independent arbiter review."
user-invocable: true
when_to_use: "Invoke when work should be split across multiple headless runtimes or in-session subagents, routed by task capability and risk, isolated where needed, and reviewed before handoff."
category: dev-tools
keywords: [orchestrate, headless, multi-agent, internal, subagents, live-routing, model-routing, capability, risk, worktree, resume, parallel, arbiter]
argument-hint: "<job-spec.yaml | task description | --resume <run-dir>> [--yes] [--internal]"
license: MIT
metadata:
  author: agentkit
  version: "1.7.1"
---

# Orchestrate

Coordinate headless coding-agent jobs and in-session subagents through a
staged, captured, resumable workflow. The skill owns routing and judgment;
`ak orchestrate` owns deterministic plan state, process supervision and
observable evidence. No service or dashboard is required.

Runtime and model catalogs drift. Resolve every route from live execution-time
evidence. Never treat a runtime, provider, model, alias, flag, or agent seen in
this file or an older report as currently available.

## Inputs

Accepted forms:

```bash
/ak:orchestrate "research three implementation options and compare them"
/ak:orchestrate "compare the auth options" --internal
/ak:orchestrate plans/orchestrate-jobs.yaml
/ak:orchestrate plans/orchestrate-jobs.yaml --yes
/ak:orchestrate --resume plans/reports/orchestrate-<timestamp>
```

Use a YAML job spec for repeatable runs. For a free-form request, create a
temporary spec at `plans/reports/orchestrate-<timestamp>/jobs.yaml` before
dispatch.

`--internal` is a routing preference, not a hard mode. It asks the selection
policy to consider in-session subagents first for jobs without an explicit
`runtime:`. A job that needs model selection, stronger enforced isolation,
or another control the current harness lacks may use a live-verified CLI
fallback. Never override an explicit runtime, model, or agent pin silently.

## Authority Map

Keep durable facts in one place:

- [model-routing.md](references/model-routing.md) is the **sole route-selection
  authority**. It owns capability tiers, risk tiers, task defaults, internal
  selection, fallback qualification, and model-family independence.
- [runtime-matrix.md](references/runtime-matrix.md) owns live candidate
  discovery, probing, command verification, OS evidence, and
  `<run-dir>/runtimes.json`.
- [harness-profiles.md](references/harness-profiles.md) owns the evidence schema
  for permissions, isolation, capture, budgets, and enablement.
- [internal-routing.md](references/internal-routing.md) owns in-session dispatch,
  capture, timeout, and resume mechanics.
- [job-spec.md](references/job-spec.md) describes the executable YAML and
  acceptance contract; Go types and validation own exact machine fields.
- [observation.md](references/observation.md) owns observation, intervention,
  diagnosis and evidence-based improvement.

Do not copy runtime or model catalogs into this file. When references disagree,
stop and report the contract mismatch.

## Pipeline

### 1. Brainstorm and intake

- Clarify the desired outcome, constraints, non-goals, and acceptance evidence.
- Read the request or job spec and identify the workspace root.
- Identify dependencies, destructive or external intent, expected outputs, and
  runtime constraints.
- Refuse any plan that would place secrets, tokens, credentials, cookies,
  private keys, dotenv values, or unrelated private data in prompts or capture.
- Prefer a direct single-agent workflow when orchestration would add no useful
  parallelism, staged dependency, runtime diversity, or arbiter value.

### 2. Build the job graph

- Convert the accepted outcome into jobs with explicit `task`, `cwd`, timeout,
  expected output, and file ownership.
- Use `depends_on` to form stages.
- Run same-stage jobs concurrently only when ownership and outputs do not
  overlap.
- Mark public-contract, security-sensitive, cross-module, or hard-to-revert
  implementation as `importance: high`.
- Set `isolation: worktree` for parallel writers, untrusted write prompts, and
  any harness whose write boundary is weaker than the job requires.
- Name the skill or instructions each headless job must load; do not rely on
  automatic skill discovery in a one-shot process.

### 3. Discover, profile, and route

- Reuse discovery evidence within a session only while runtime binary/version, account, host, permissions, requested controls and model catalog remain unchanged. Invalidate on changes or probe failures; resume must reconcile existing attempts before dispatch.
- Build a live runtime inventory per
  [runtime-matrix.md](references/runtime-matrix.md).
- Profile each candidate per
  [harness-profiles.md](references/harness-profiles.md).
- Pass the live evidence and job classification to
  [model-routing.md](references/model-routing.md).
- Record the selected runtime, model or agent, capability tier, risk tier,
  controls, evidence source, and fallback reason.
- A missing, unauthenticated, unverified, or insufficiently controlled
  candidate cannot satisfy a route.
- Re-profile fallbacks and rebuild their commands; never carry model names or
  flags between runtimes.
- Mark the job `blocked` when no candidate meets both capability and risk
  floors. Never budget-route judgment or silently weaken safety.

### 4. Apply the safety gate

- Confirm every job's cwd, allowed files, writable roots, and expected side
  effects.
- Use least-privilege permission and tool controls verified on the live runtime.
- Keep every permission-bypass mode disabled by default.
- Record existing user authorization and its exact scope in `authority`.
  Request approval only for an action outside that scope; ordinary prior
  authorization remains valid without repeating `--yes`. A nonempty reference
  records the decision; it cannot grant authority by itself.
- Treat inherently auto-approved headless modes as constrained. Limit them to
  read/report work or R2-isolated writes; never shared-tree destructive work.
- Remember that a worktree prevents edit collisions but is not an OS sandbox.
- Give every CLI process an external timeout. Treat internal timeouts as
  accounting-only unless the current harness proves cancellation.

### 5. Dispatch, observe and verify

- Create required worktrees, resolve explicit input handoffs and pin each cwd.
- Resolve each CLI invocation from the live profile, with argument arrays and
  scoped tools. Prepare with `ak orchestrate prepare <jobs.yaml> <run-dir>`;
  advance with `ak orchestrate advance <run-dir> --json`.
- Persisted attempts and intended supervisor IDs precede launch. Advance
  reconciles existing work before dispatch; never bypass an uncertain attempt
  by calling start manually. Follow [job-spec.md](references/job-spec.md).
- Dispatch returned internal jobs through the native harness, preserving their
  attempt IDs. Store handles and capture per
  [internal-routing.md](references/internal-routing.md); accept only a settled
  attempt with verified artifacts and checks.
- Read `status`, `events --after <cursor>` and `output --offset <bytes>` for
  supervisor run IDs. Keep each run's cursor separate. Poll until
  `all_settled`, not merely an aggregate failed status.
- Supervisor deadlines and bounded redacted capture survive the client exit
  on supported platforms. Unsupported process supervision remains an explicit
  capability gap; use a different qualified host/harness for jobs requiring it.
- Apply the observation admission and intervention contract in
  [observation.md](references/observation.md). A quiet process is not proof of
  a stall. A cancelled request is not proof of a stopped writer.
- Retry only within declared bounded policy after safe settlement and unchanged
  fingerprints. Unknown flags/models require fresh discovery; permission or
  external-effect failures require a scope-aware decision, not blind retry.

### 6. Run an arbiter review

- Wait for all runnable jobs to settle.
- Use a separate C3 judgment route selected by
  [model-routing.md](references/model-routing.md).
- Prefer independently configured or different-family review when live
  evidence proves it; disclose a same-family fallback.
- Compare each result with `expected_output` and the original intent.
- Run the checks listed in the spec.
- Flag contradictions, unsupported claims, missing artifacts, safety gaps,
  timeouts, and failed checks.
- Do not summarize unverified work as complete.

### 7. Report

- Write `plans/reports/orchestrate-<timestamp>/report.md`.
- Include per-job status, selected capability/risk tier, resolved runtime and
  model or agent, artifacts, errors, arbiter verdict, checks, reproduction
  commands, worktree diffs awaiting integration, and unresolved questions.
- Record effective model/effort, startup/fork/communication time and cache telemetry when exposed, alongside full retries and cost. Unknown cache cost is not zero; none of these observations may lower capability/risk floors or override explicit pins.
- Preserve per-attempt metrics in the run; aggregate comparable run records
  for cross-run analysis without changing their evidence.
- Never let metrics or a previous run silently rewrite routing policy.

## Routing Invocation

After live inventory and profiling, invoke
[model-routing.md](references/model-routing.md) and record its resolved route.
Do not restate, override, or infer its task defaults, tier floors, candidate
ranking, internal-agent choice, or fallback rules elsewhere.

## Worktree Isolation

- Create one worktree per isolated job from the accepted base ref.
- Use a unique branch under the run namespace and set the job's cwd to that
  worktree.
- Never share a worktree across jobs or reuse a failed attempt without an
  explicit cleanup/recovery decision.
- Sequence jobs that must edit the same generated artifact, lockfile,
  migration sequence, or shared configuration. Separate worktrees defer those
  conflicts; they do not resolve them.
- Integration is coordinator-owned and happens only after the arbiter pass.
  Summarize diffs first; merging or cherry-picking is a separate reviewed step.
- Remove only integrated or explicitly discarded worktrees. Preserve failed
  worktrees for diagnosis and list them in the report.

## Metrics and Self-Improvement

Load `references/metrics-and-self-improvement.md` when comparing run
outcomes or considering a routing-policy change.

## Job Spec

Read [job-spec.md](references/job-spec.md) for the full schema. The abbreviated planning
example below uses placeholders; add the executable fields described there
after live discovery before passing it to `prepare`:

```yaml
version: 1
concurrency: 2
jobs:
  - id: scout-session-api
    runtime: internal
    task: scout
    cwd: <workspace-root>
    prompt: "Inspect the session API and report extension points."
    timeout: 10m
    expected_output: "Markdown report with files read and recommended seams."

  - id: independent-review
    runtime: <verified-cli-runtime>
    fallback_runtime: [<verified-fallback-runtime>]
    task: review
    cwd: <workspace-root>
    prompt: "Review the proposed change and verify its evidence."
    timeout: 10m
    expected_output: "Independent verdict with checks and unresolved risks."
```

Do not replace placeholders from memory. Resolve and record them during that
run.

## Safety Defaults

- Every job has an explicit cwd, timeout, expected output, and ownership.
- Capture stays under `plans/reports/orchestrate-<timestamp>/`.
- Redact secrets and sensitive values from prompts, commands, logs, and reports.
- Start with read-only or scoped-write behavior.
- Permission bypasses remain off unless the user approved the exact action and
  a stronger external isolation boundary contains the residual risk.
- Parallel writers use separate worktrees and disjoint ownership.
- Preserve failed output for diagnosis; never hide or relabel it.
- Keep destructive and credentialed external actions off prompt-only internal
  isolation.

## Output Layout

Load `references/output-layout.md` for the run-directory and supervisor
capture tree and the rules on exporting private graphs or job specs.

## Arbiter Checklist

Load `references/arbiter-checklist.md` at step 6; the final report is
blocked until every question in it is answered.

## Failure Modes

Load `references/failure-modes.md` when a job fails, times out, requests
permission, is interrupted, or ownership or references disagree.

## Limitations

- Jobs do not share implicit memory; pass required artifacts through explicit
  dependencies.
- Internal jobs may not support force cancellation, per-job sandboxing, or
  model selection.
- CLI commands, models, authentication, and safety behavior drift; every run
  revalidates them.
- Worktrees require a git repository and disk headroom and do not provide
  process isolation.
- Metrics are advisory and cannot authorize an automatic route-policy change.
- Orchestrate coordinates existing runtimes; it does not add a daemon,
  dashboard, account pool, or provider adapter.
- `ak orchestrate` process supervision requires Darwin. Discovery and historical
  observation do not imply equivalent lifecycle support elsewhere. Record the
  actual host and harness control limits in every route.

## Completion Report

End with:

```markdown
**Orchestrate Result**
- Spec: <path or inline request>
- Report: <plans/reports/orchestrate-.../report.md>
- Jobs: <success>/<failed>/<blocked>
- Arbiter: pass|fail|blocked
- Checks: <commands or none>

Unresolved questions:
- None
```
