---
name: ak:frontend-design
description: Create polished frontend interfaces from designs/screenshots/videos. Use for web components, 3D experiences, replicating UI designs, quick prototypes, immersive interfaces, avoiding AI slop.
user-invocable: true
when_to_use: "Invoke when visual fidelity and polished UI are primary."
category: design
keywords: [ui, design, screenshots, prototyping]
license: Complete terms in LICENSE.txt
argument-hint: "[prompt|image-path|component]"
metadata:
  author: agentkit
  version: "2.0.3"
---

# Frontend design

Deliver working interfaces that fit the user's purpose, brand and reference, with clear
hierarchy, responsive layout, accessible controls and complete interaction states.

## Choose the design contract first

| Intent | Route |
|---|---|
| Preserve or improve existing UI | Inspect existing tokens/components; preserve accepted taste and behavior |
| Replicate screenshot | `references/workflow-screenshot.md`; source fidelity governs composition |
| Replicate video | `references/workflow-video.md`; match relevant motion and states |
| Describe without coding | `references/workflow-describe.md` |
| New interface | Establish purpose, audience, content, constraints and art direction; optionally use `references/aesthetic-recipes.md` |
| 3D/WebGL | `references/workflow-3d.md` |
| Quick implementation | `references/workflow-quick.md` |
| Complex immersive work | `references/workflow-immersive.md` |

Use the actual project stack and existing design system. Ask only about a missing decision
that materially changes the result. Seeded variation, layout quotas and motion are optional
exploration techniques; never let prompt length or a quota overturn accepted taste.

## Quality and completion

Use real content and working assets; do not fabricate metrics, testimonials or functionality.
Define coherent typography, color, spacing and hierarchy using existing tokens when present.
Provide default, hover, focus-visible, active, disabled, loading and error/success states
where applicable. Use semantic controls, keyboard access, visible focus, readable contrast,
adequate touch targets and reduced-motion alternatives whenever animation is used.
Keep content visible if animation or JavaScript fails. Motion must serve feedback or meaning.

Inspect the rendered result at the required mobile and desktop sizes; compare replication
against its source. Check overflow, text wrapping, asset loading, interaction behavior and
relevant build/tests. Fix failures and report unverified dimensions honestly. Aesthetic
recipes guide exploration; visual fidelity, brand fit, usability and function decide acceptance.
Use `../ak-design/references/handoff-gate.md` for the final artifact handoff when needed.

## Asset & Analysis References

| Task | Reference |
|------|-----------|
| Generate assets | `./references/asset-generation.md` |
| Analyze quality | `./references/visual-analysis-overview.md` |
| Extract guidelines | `./references/design-extraction-overview.md` |
| Optimization | `./references/technical-overview.md` |
| Motion timing, GSAP/Motion recipes | `./references/motion-craft.md` |
| Animations (anime.js) | `./references/animejs.md` |
| Shared anti-slop preflight (other design skills) | `./references/design-quality-preflight.md` |
Quick start: `./references/ai-multimodal-overview.md`

**Assets**: Generate images with `ak:ai-multimodal`, process with `ak:media-processing`
