# Conversation header research

Research conducted: 2026-10-02, Asia/Singapore. Application baseline: `239d476eea9e9f74463cd365f4ae2e4445330e47`.

## Summary

Recommend one candidate-focused header and a labelled reply-mode control near the composer. On phones, show the global navigation bar in the inbox and other pages; an open conversation uses its own Back control. Preserve the desktop sidebar and top-bar appearance.

The problem is structural. The old header combines navigation, candidate details, channel, reply policy, diagnostics and destructive actions. Its mobile CSS removes the reply-mode label and dropdown arrow, leaving a person/robot symbol in nested circles. Restyling that symbol does not clarify the action. At 390×844 the global bar occupies 56px and the conversation header 86.5px, leaving 142.5px above the transcript.

## Method and evidence

Reviewed application markup, mode policy, capability slots, responsive CSS, and the populated local view. Research used five bounded web calls across the team, prioritizing vendor documentation and primary usability/accessibility guidance. Vendor documents were consulted for workflow principles, not copied as pixel layouts. NNGroup's icon study is dated October 2024; vendor help pages are maintained documents without a stable publication date. W3C's enhanced target guidance was current when retrieved. Apple toolbar guidance was available through official search excerpts; its full page required JavaScript, so it is supporting context rather than the basis for numeric claims.

- Icons must communicate meaning in context, not merely depict a recognizable object. An ordinary person icon can mean profile, assignment, takeover or reply mode. A visible mode label removes this ambiguity. [NNGroup icon evaluation](https://www.nngroup.com/articles/how-to-test-digital-icons/).
- Reply operations are grouped around composition in documented support workflows. Zendesk documents its channel selector in the composer; Intercom documents Reply/Note and message actions there. Moving our reply-policy control beside writing is a design inference from those workflows, not a claim that their controls are equivalent to ours. [Zendesk messaging](https://support.zendesk.com/hc/en-us/articles/4408843683226-Receiving-and-sending-messages-in-the-Zendesk-Agent-Workspace), [Intercom conversations](https://www.intercom.com/help/en/articles/6433002-start-a-conversation-from-the-inbox).
- Assignment and automation takeover are distinct. Intercom explicitly distinguishes assigning a teammate from interrupting automation. Our implementation must retain the existing claim action and three-way reply policy rather than replacing them with a decorative binary switch. [Intercom assignment](https://www.intercom.com/help/en/articles/6561699-assign-conversations-to-teammates-and-teams).
- Keep this project's 44×44 CSS-pixel targets. That size corresponds to WCAG's enhanced AAA criterion; WCAG 2.2 AA minimum is 24px with exceptions. A visually small channel glyph is not itself an interactive target. [W3C enhanced target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-enhanced.html), [W3C minimum target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum).

## Options and trade-offs

| Approach                                                | Benefits                                                                                          | Costs and risks                                                                                   | Decision        |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | --------------- |
| Restyle the existing single row                         | Small source change; familiar layout                                                              | Continues squeezing identity and mode in a narrow pane; icon remains ambiguous if label is hidden | Reject          |
| Identity row plus permanent mode row at the top         | Clear labels; mode is always prominent                                                            | Adds header height; operational state still competes with identity                                | Viable fallback |
| Candidate header plus reply-mode toolbar at composition | Clear separation of identity and writing; retains explicit state and takeover; saves header space | Requires a small presentation slot and checking footer sizing/scroll behavior                     | Recommended     |
| Hide mode changes in overflow                           | Lowest visual density                                                                             | Frequent intervention becomes harder to find; mode is less visible before replying                | Reject          |

Keeping both mobile bars maximizes immediate access to global navigation but consumes 56px inside a focused task. Hiding the global bar only while a phone conversation is selected gives that space to the conversation; Back returns to the inbox and global navigation. Desktop has enough space and keeps its intended continuous chrome.

## Implementation requirements

- One candidate identity target, preserving profile-name-first header identity. Keep the channel account identity and phone number readable; show a truthful missing-phone state.
- Back on phone; overflow only for real secondary actions. Admin diagnostics and deletion retain existing permission checks.
- Labelled `Chatbot`, `Tư vấn viên`, and `Bán tự động` options near the composer. Preserve unclaimed-human restrictions and explicit `Tiếp quản` behavior. A configured bot mode is not evidence the bot is currently processing a message.
- One static closed status; no disabled dropdown beside a duplicate closed badge.
- Keep parent orchestration, candidate deep links, focus restoration and capability slots. Expose presentation-only components and one optional toolbar slot; no new transport or domain dependencies.
- Preserve the stable composer footer and its measured scroll reserve. No fixed-position composer or hard-coded keyboard height.
- Adapt to the conversation pane's width, including narrow tablet panes beside the directory. Keep candidate metadata legible, a visible dropdown label and 44px interactive targets.
- Gate candidate actions by actual panel availability, including the standalone view.

## Verification

The populated local view has zero document horizontal overflow at 320, 360, 390, 768 and 1440px. At 390px the selected conversation header measures 79.9px; the mobile global bar is hidden. The 56px global bar restores on Back. At 768 and 1440px it remains visible, with the protected desktop appearance. Mode controls and phone navigation have 44px targets. The closed conversation has one static status and no reply-mode dropdown or composer.

Keyboard candidate-panel return focus and explicit successful takeover-to-composer focus were verified through CUA. Presentation, parent orchestration, transcript and responsive regressions pass all 61 focused tests. Mode reconciliation regressions pass 22 tests across three files. The adjacent completion report records final navigation, full-suite and real-backend E2E outcomes. Before/after screenshots, geometry, logs and the binary patch are exported under `plans/exports/`.

## Unresolved questions

Local Chromium checks establish layout and behavior, not recruiter usability outcomes. A later task-based review with recruiters should measure candidate lookup and takeover discoverability. Safari/Firefox, live provider delivery and production behavior remain outside local UI verification.
