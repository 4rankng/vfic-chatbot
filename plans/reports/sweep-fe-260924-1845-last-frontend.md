# sweep-fe — last two frontend tickets (FE-17, FE-19)

FE-19 landed as `8fd480c1` and FE-17 needed no second implementation: the resumed FE session
landed the registry fix (`021a7155`) while I was independently verifying it, and my verification
confirms theirs. `npm run registry:check` is green (243 manifest files), `node scripts/generate-registry.mjs`
is idempotent against the checked-in `registry.json`, and the `Registry paths` step now runs in the
`frontend-quality` CI job. The frontend unit lane is fully green: 111 files / 597 tests, lint 0
errors, typecheck clean.

## FE-17 — registry.json vs the generator (no commit from me)

The checkpointed WIP in my lane (registry.json + generate-registry.mjs) was already the correct
fix shape: the generator emits `registry:style` and svg-asset entries, excludes test-only wrappers
on every glob, and no longer pins the deleted `CHANGELOG.md`. I verified it rather than re-implementing
it: ran the check (green, 243 files), ran the generator twice (no diff), and matched each of the
ticket's 16 cited errors to the fix (PerformanceTrendChart and the channel-adapter SVGs are now
manifest entries; the missing-CHANGELOG error is gone because the entry is). The resumed session
committed that WIP as `021a7155` with the CI gate, and moved the card to DEV_COMPLETED. Nothing
further owed.

## FE-19 — chatops.css scoped under the knowledge workspace (`8fd480c1`)

The open FE-19 work after `88e3866d` (the ratchet) was folding actual sheets. I folded the one
sheet whose fold is provably rendering-neutral, and the analysis that got there is the useful
output for the remaining 689 rules:

- The ratchet only counts depth-0 selectors — rules inside `@media` blocks are invisible to it
  (verified by recount). Any future fold that scopes only the depth-0 rules of a sheet whose own
  media queries re-declare the same selectors flips those desktop/mobile overrides; sheets must be
  folded wholly or not at all.
- Compound-class scoping raises specificity by one class, and the redesign layers
  (`tailkit-redesign.css`, `untitledui-conversations.css`) load last in `inbox.css` precisely to win
  ties. Scoping `conversation-list.css` (47 rules) flips 28 conflicting (selector, property) pairs;
  `chat.css` 64, `context-drawer.css` 22. Folds need the competing later-file rules raised by the
  same compound class — cascade balancing, not blind prefixing.
- Classnames cross roots: persona directory rules style the settings-embedded `PersonaList`
  (`EmbeddedSettingsSections.tsx`), `personas-project.css`'s live rules render in the projects
  screen, and ~19 of its 22 rules are dead selectors. A fold must audit render sites first.

`chatops.css`'s two `.ops-status-strip` rules survived all three traps: the strip renders only in
`KnowledgeSourceList.tsx` inside the existing `.inbox-bg-container.knowledge-workspace` root, and
their only real competitor was personas-responsive.css's narrow-screen `.knowledge-status-strip`
repeat(4) override, deliberately double-written to out-rank the old (0,2,0) form. Both sides were
raised by the same compound class, so every cascade winner is unchanged.

Verification beyond the source-text CSS tests (TEST-10's complaint): a throwaway e2e spec drove the
disposable backend harness to the knowledge screen and compared the strip element pixel-exactly
(`maxDiffPixelRatio: 0`) on `visual-desktop` and `visual-mobile`, before vs after the edit — identical.
A control run (pre-edit sheet vs same baselines) also surfaced that the mobile full-page screenshot
varies run-to-run with list timing (~70px shift), which is why the element-scoped comparison is the
meaningful one. Throwaway spec and snapshots were deleted before the commit; nothing e2e-side was
committed.

## Boundary tests

No backend files touched; the red boundary tests reported at handover belong to the FE session's
in-flight frontend/src refactor (their WIP is uncommitted in the tree right now — flagged to the
team-lead before my commit). My commit's files are clean in `git status`, and the full app unit lane
passes on the tree as it stands, FE WIP included.

## fe565f9d factual note

`fe565f9d` was not my commit. My only commit attempt before `8fd480c1` failed with "no changes added
to commit" (exit 1) — the registry WIP had already been committed by the other session. From my
transcript I authored exactly one commit this session: `8fd480c1`. The lead's mislabel correction
covers the ARCH-01 work that rode along in `fe565f9d`.

Status: DONE_WITH_CONCERNS
Summary: FE-19 folded safely with pixel-exact visual proof (8fd480c1, ratchet 691→689); FE-17 verified
green after landing from the parallel session (021a7155) — nothing further owed on it.
Concerns: 689 unscoped rules remain by design (card forbids the batch rewrite); every remaining sheet
needs render-site + cascade-balancing analysis before folding — the mechanics are documented above and
in the chatops.css comment. The concurrent FE session's uncommitted frontend/src WIP sits in the shared
tree and its ratchet-relevant CSS edits are unreviewed by me.
