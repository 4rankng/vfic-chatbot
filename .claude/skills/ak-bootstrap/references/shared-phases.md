# Shared Phases (All Modes)

These phases apply after planning is complete and cook skill is activated.
Cook skill handles most of these — this reference documents bootstrap-specific guidance.

## Implementation

Handled by **ak:cook** skill. Bootstrap-specific notes:
- Use main agent to implement step by step per plan in `./plans`
- Use `ui-ux-designer` subagent for frontend, following the project's discovered design guidance
- Asset pipeline: `ak:ai-multimodal` (generate/analyze) → `imagemagick` (crop/resize) → background removal if needed
- Run type checking and compile after each phase

## Testing

Handled by **ak:cook** skill. Bootstrap-specific notes:
- Write real tests — NO fake data, mocks, cheats, tricks, temporary solutions
- `tester` subagent runs tests → report to main agent
- If failures: `debugger` subagent → fix → repeat until all pass
- DO NOT ignore failed tests to pass build/CI

## Code Review

Handled by **ak:cook** skill. Bootstrap-specific notes:
- `code-reviewer` subagent reviews code
- If critical issues: fix → retest → repeat
- Report summary to user when all tests pass and code reviewed

## Documentation

After code review passes, use the `docs-manager` subagent only when the change
has documentation impact. Discover the owning documentation from repository
instructions and navigation, then update the smallest justified surface. Do not
create or refresh a fixed document inventory.

Use the `project-manager` subagent to update the active plan or phase record.
Plans are execution state, not evergreen product documentation.

## Onboarding

Guide user to get started with the project:
- Ask 1 question at a time, wait for answer before next
- For required credentials, explain the secure environment/secret-store setup; check presence without asking the user to paste the value into chat
- If user requests config changes, repeat until approved

## Final Report

1. Summary of all changes, brief explanations
2. Guide user to get started + suggest next steps
3. Commit/push only when requested or already authorized; bootstrap alone does not authorize publication. Reuse existing authorization and report remaining setup precisely.

**Report rules:**
- Lead with the outcome. Keep reports short by being selective, not by compressing the writing into fragments or arrow chains; write complete sentences.
- List unresolved questions at end, if any
