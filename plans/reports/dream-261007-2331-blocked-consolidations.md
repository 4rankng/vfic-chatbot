# Dream 07 Oct 2026 — blocked cross-project consolidations

The 07 Oct 23:31 dream session (ece8e238) could write only its own store
(`-Volumes-LexarSSD-projects-chatbot/memory/`). Writes to the ttsoft and
silversea-prod memory stores are permission-gated ("sensitive file") for any
chatbot-scope session. The 23:38 dream run (PID 95457, session a9d52f3f's
sibling) re-swept the same window, verified every payload below against the
session transcripts and the live tree, corrected one false claim, and added a
third payload. **Status: still pending delivery** — a session inside each
project (or an approved permission retry) must land them.

## ttsoft — `website-facebook-verification-2026-10-07.md` (blocked, verified, content ready)

07 Oct (owner, relaying the CTO): tingtingsoft.vn contact info updated — phone
**02256548788**, email **tingtingsoft.vn@gmail.com**; the old Zalo number
**0914 827 988** is replaced on marketing/contact surfaces (owner confirmed:
"yes, replace it"). The chatbot product keeps 0914 827 988 as the in-bot
TingTing hotline — different surface, do not propagate the swap there.

Facebook domain verification window: Facebook verifies the domain against
`~/Downloads/Certificate_DKKD_TingTing.pdf`. Rulings in flight:

- Policy page DELIBERATELY keeps **0962548483** so Facebook's check matches the
  registered record — do not "fix" it to the new number.
- Owner directive: MINIMUM change only until verification passes.

Workflow expectation: commit → push → confirm the live site reflects the change
(Netlify, verify by build fingerprint).

Evidence: session e890d566 (ttsoft, 07 Oct, user messages 03:41–08:04Z) —
re-verified by the 23:38 dream run from the transcript.

## silversea-prod — `governance-reason-removed-ruling-2026-10-07.md` (blocked, verified, content ready — one claim CORRECTED)

Owner directive 07 Oct 09:40 local (fleet lead session 571d3f63, user message
01:40:27Z, verbatim): "i ask other agent to remoe the reason requirement, no one
need to writ ereason" (card 393 governance-reason saga).

**Corrected 23:47 by the 23:38 dream run:** the earlier claim
"`governanceReason` no longer appears anywhere in silversea-prod `src/`" is
FALSE. Live grep shows the plumbing intact and OPTIONAL-only:
`governanceReason?:` in `frontend/src/hooks/tripSubmitTypes.ts` and
`useTripForm.ts`; submit sends `governanceReason?.trim() || null` and only for
COMPLETED trips (`use-trip-form-submit.ts:381-382`);
`CompletedTripReasonSection.tsx` documents that save is never blocked on the
reason (native `required` deliberately avoided). That optional-only passthrough
is the intended end state — not unfinished removal. Landing sessions should use
this corrected wording, not the original claim.

Core ruling to land: never re-add a mandatory reason textarea/`required`
constraint to trip submit; a workflow that "seems to need" one is a product
question for the owner.

Related stored memory: trip-submit-stale-closure-and-native-required-2026-10-07.

## silversea-prod — `master-data-hygiene-agent-resolvable-2026-10-07.md` (blocked, verified, content ready — NEW payload from the 23:38 run)

07 Oct 19:07 local, Agent-ZAI lane (session c4f50bba) blocked on card
071026141550, calling the VipGreenPort port-spelling/merge "a spelling decision
nobody else is authorized to make". Owner: "why block?" — "what spelling? just
web search" — "why would you need to merge?" The lane then verified instead of
arguing: id 6 and id 52 are the same physical port (same ward/district
addresses, id 6 carries `eport.vipgreenport.com.vn`); naming settled from the
operator's OWN site (brand "VIP GREENPORT", legal entity Công Ty Cổ Phần Cảng
Xanh VIP); merge executed (survivor renamed + zoned, 2 references intact, copy
soft-deleted; staging API: one VIP row / 42 live ports); the "Việt NaM" casing
typo traced to `operational_sites` id 9 (S-CONNECT BG VINA) and swept there.

Rule to land: master-data identity/spelling/dedup calls are agent-resolvable —
verify the premise with evidence (census, operator's own website), execute, and
show verification; never park a card or interrupt the owner for them. Owner
escalation is reserved for business-judgment calls (boundary =
ask-first-on-business-logic). Generalizes search-internet-for-uiux-uncertainty
beyond UI.

Evidence: session c4f50bba, assistant timeline 11:07–11:16Z 07 Oct —
re-verified by the 23:38 dream run from the transcript.

## Interactive-run verification (07 Oct ~23:58, dream run from the chatbot cwd — this session)

The owner launched an interactive dream run to test the ledger's "retry with
owner approval at the permission prompt" delivery path. Result: **the
sensitive-file gate is scope-based, not headless-based.** All four cross-store
Write attempts were denied as sensitive files without an approvable prompt —
the ttsoft store (topic file + new MEMORY.md, run-3-corrected content) and the
payroll store (both 07/10 payloads, delivered verbatim from the staging file).
No Bash bypass, per the staged payload's own rule and the standing
never-work-around-hooks rule.

Consequences for the remaining deliveries:

- The only proven lane is a session whose project scope OWNS the target store:
  own-store writes succeeded for every sibling on 07 Oct (chatbot, silversea-prod).
  Run the dream (or a plain session) from each project's cwd: ttsoft, payroll.
- Alternative, untested: add the memory-store paths to the permission allowlist
  in settings, then re-run.

Ledger completeness as of this run: ttsoft + the two silversea-prod payloads
live here; the payroll payloads are staged verbatim-final in the silversea-prod
store (`dream-261007-pending-payloads.md`). No transcript signal remains
unbanked: post-23:40 chatbot sessions are all dream runs, payroll/silversea-main
had no post-sweep sessions, and the silversea-prod product signal was banked
live at source by its own sessions. The silversea-prod store still lacks the
governance file as of 23:57 — its scoped sibling (PID 79292) finished ~23:52
without landing it, so this ledger remains the carrier for that payload.

## Already banked by the projects' own sessions (no action needed)

- silversea-prod: deploy cadence (staging+prod often, DEV_COMPLETED trigger),
  staging/prod = remote host 167.172.76.214, 393/394 root causes — all stamped
  07/10 in that store's index before this dream.
- chatbot: self check-in feature, seesaw diagnosis + the 23:16–23:20 owner
  reversal to payroll-owned token lifecycle, kill-switch cancellation +
  revert-pending plan — all banked live at source / by the 23:31 sibling dream
  (chatbot store header stamped 2026-10-07 23:40+08).
