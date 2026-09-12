# New-design techniques

Use only for new art direction or requested exploration. These recipes are optional; preserve/replicate routes follow their existing system/reference.

## Design Dials

Three configurable parameters that drive design decisions. Set from the preset table (or user override via chat):

| Dial | Default | Range | Low (1-3) | High (8-10) |
|------|---------|-------|-----------|-------------|
| `DESIGN_VARIANCE` | 8 | 1-10 | Perfect symmetry, centered layouts, equal grids | Asymmetric, masonry, massive empty zones, fractional CSS Grid |
| `MOTION_INTENSITY` | 6 | 1-10 | CSS hover/active states only | Scroll reveals, spring physics, perpetual micro-animations |
| `VISUAL_DENSITY` | 4 | 1-10 | Art gallery — huge whitespace, expensive/clean | Cockpit — tiny paddings, 1px dividers, monospace numbers everywhere |

Presets by surface (variance/motion/density): SaaS landing 7/6/4 · agency/creative 9/8/3 · premium consumer 7/6/3 · designer portfolio 8/7/3 · dev portfolio 6/5/4 · editorial 6/4/3 · dashboard/product UI 3/2/6 · public sector 3/2/5. Redesigns: infer the existing page's dial values first; preserve-mode matches them, overhaul-mode chooses values from the new brief.

Dial suggestions: higher variance can explore split or asymmetric layouts; higher density can use spacing and hairlines. Neither setting bans centered heroes or cards. Motion is optional at every setting and must respect reduced-motion preferences when used.

## Register: Brand vs Product

Identify the register before designing — the rules differ:

| | **Brand** (landing, marketing, portfolio) | **Product** (app UI, dashboard, tool) |
|---|---|---|
| Slop test | "Would someone say AI made that?" — bar is distinctiveness | "Would a Linear/Figma-fluent user trust it?" — bar is earned familiarity |
| Type scale | Fluid `clamp()`, ratio ≥ 1.25 | Fixed `rem`, ratio 1.125–1.2; one family often right |
| Color | Committed/Full/Drenched strategies allowed — one saturated color owning a hero is voice | Restrained floor: accent = primary action + selection + state, nothing else |
| Motion | One orchestrated page-load entrance allowed | 150–250ms state-conveying only; page-load choreography avoid |
| Layout | Asymmetry, grid-breaking, art direction per section | Density, consistency, structural responsiveness (collapse sidebar, not shrink type) |
| Failure mode | Restraint without intent reads as mediocre | Strangeness without purpose destroys trust |

## Design Thinking

For exploratory art direction, consider:
- **Purpose**: What problem does this interface solve? Who uses it?
- **Tone**: Possible tones include: brutally minimal, maximalist chaos, retro-futuristic, organic/natural, luxury/refined, playful/toy-like, editorial/magazine, brutalist/raw, art deco/geometric, soft/pastel, industrial/utilitarian, etc.
- **Constraints**: Technical requirements (framework, performance, accessibility).
- **Differentiation**: What gives this content a recognizable identity? What's the one thing someone will remember?

**CRITICAL**: Choose a clear conceptual direction and execute it with precision. Bold maximalism and refined minimalism both work - the key is intentionality, not intensity.

### Optional exploration procedure

For a new design needing exploration, choose the techniques that serve the brief:

1. **Design Read declaration** — one line: `Reading this as: <page kind> for <audience>, with a <vibe> language, leaning <aesthetic direction>.` Use this optional summary when it clarifies an unresolved brief; reuse clear requirements without another question.
2. **Seeded variation (break mode collapse)** — when the user wants variation, choose a reproducible seed independent of prompt wording and use it to sample the menu below, then pick the hero archetype and 2-3 component patterns from that direction. Preserve an accepted direction, font pairing and palette across iterations. If the seeded pick is a poor fit for the audience, step to the adjacent row and say so — choose based on audience and brand fit.
3. **Aesthetic thesis** — one sentence: `<direction> for <audience>: <palette in 5 words>, <type character>, <layout signature>, <one memorable element>`. Also state where the form came from in the CONTENT (a motif, a domain object, a word in the copy). Use it only if it helps explain the selected direction.
4. **Tokens first** — CSS variables for colors (OKLCH), font families, type scale, spacing scale, radii, shadows, easings. Every value in the implementation traces to a token. No ad-hoc hex codes or magic pixels mid-file.
5. **Optionally emphasize one dimension** to a memorable extreme (type scale, color, layout, motion, or density). Keep the others disciplined and quiet. Choose intensity for the audience and task.
6. **If you cannot justify a value, re-derive it from the scale.** "It looked about right" is not a justification.

## Aesthetic Direction Menu

When designing from scratch, consider a coherent direction, then execute it fully. A restrained design can be appropriate. These are **anchors, not recipes** — re-derive exact palette values from the actual brand/content, and rotate: preserve the chosen direction across iterations.

| Direction | Display / Body fonts | Palette recipe | Layout signature |
|-----------|---------------------|----------------|------------------|
| Swiss / editorial | Archivo Expanded, Schibsted Grotesk / Libre Franklin | Bone `#F7F5F0` bg, ink `#1A1815` text, single red or cobalt accent | Hairline dividers, exposed grid, flush-left, big margins |
| Luxury / refined | Libre Caslon Display, Italiana / Figtree | Deep charcoal or cream bg, gold/bronze accent, muted warm neutrals | Centered serif display, generous whitespace, thin rules |
| Brutalist / raw | Archivo Black, Bricolage Grotesque / JetBrains Mono | Unmixed primaries on white or near-black, hard `2-3px` borders, `4px 4px 0` shadows | Visible borders, no rounded corners, stacked blocks, marquee text |
| Retro-futuristic / terminal | Chakra Petch, Orbitron / JetBrains Mono | Phosphor green or amber on `#0C0F0A` tinted black, scanline texture | Monospace tables, ASCII dividers, status-bar chrome |
| Organic / natural | Gloock, Young Serif / Nunito Sans | Moss, clay, sand, cream — desaturated earth ramp, no pure white | Blob/arch shapes, irregular grid, photography-forward |
| Soft / pastel play | Baloo 2, Quicksand / Karla | Cream bg, 2-3 chalky pastels + one saturated pop | Pill shapes, chunky radii `16-24px`, pressed-button 3D (`box-shadow: 0 4px 0` + active `translateY(4px)`) |
| Industrial / utilitarian | Barlow Condensed, Oswald / Source Sans 3 | Concrete grays tinted cool, safety-orange or yellow accent | Dense data tables, uppercase labels, corner brackets |
| Art deco / geometric | Marcellus, Poiret One / Josefin Sans | Black + champagne + one jewel tone | Symmetric frames, inline SVG line ornament, letter-spaced caps |
| Editorial dark / cinematic | Bodoni Moda, Literata / Hanken Grotesk | `#101014` blue-tinted black, warm white text, one desaturated accent | Full-bleed imagery, overlapping type, huge display sizes |
| Neo-grotesque product | Familjen Grotesk, Sora / Geist | Tinted off-white bg, near-black text, one confident brand hue | Split-screen hero, asymmetric 5/7 grid, floating detail cards |

Verify chosen fonts exist on Google Fonts (or self-host an equivalent); if the content is Vietnamese or CJK, confirm the subset support before committing.

## Craft techniques

Numeric recipes below are starting points for new art direction, not quotas. User preferences, brand, content, accessibility and existing system govern the result.

**Typography**
- Max 2 families: one display, one body — paired on a CONTRAST axis (serif + sans, geometric + humanist, or one family in multiple weights). Avoid accidental font mismatches. Max 3-4 weights; preload only the critical body weight.
- Modular scale by register: 1.2 (dense UI), 1.25 (default web), 1.333 (editorial/marketing). Use additional size steps only for a clear role.
- Body: 16-18px in `rem`, line-height 1.5-1.7, measure 45-75ch (65ch sweet spot). Headings: line-height 1.1-1.2. Heading:body size ratio ≥ 2.5x.
- Display type is large but capped: `clamp(2.75rem, 6vw + 1rem, 6rem)`. Above ~6rem the page is shouting. Letter-spacing floor: **≥ -0.04em** (-0.02 to -0.03em is plenty for tight grotesque display; tighter and letters touch). ALL-CAPS micro-labels: +0.05 to 0.12em at 11-12px.
- **Headline wrapping**: a 2-3 line hero can be readable. Use a wide container (`max-w-5xl`/`max-w-6xl`) and shrink the font before letting it wrap to 4+ lines. Longer copy or narrower viewports may need more lines; check the actual result.
- `text-wrap: balance` on h1-h3; `text-wrap: pretty` on prose — free typographic quality.
- Dark mode compensation (light-on-dark reads heavier): line-height +0.05-0.1, letter-spacing +0.01-0.02em, drop body weight one notch (400 → 350 if available).
- `font-variant-numeric: tabular-nums` for data, prices, counters, tables.
- Multilingual: put the Latin font FIRST in the fallback chain (`"Geist", "Noto Sans SC", sans-serif` — matching is per-codepoint). CJK: +0.2 line-height over Latin values, never negative tracking. Vietnamese: verify diacritics render in the chosen face. Inputs ≥ 16px font (avoids mobile zoom).

**Spacing**
- Example 4pt scale: 4, 8, 12, 16, 24, 32, 48, 64, 96. Preserve an existing scale or content-driven exception.
- Proximity encodes hierarchy: 8-12px between related siblings, 48-96px between sections — intra-group gap < inter-group gap by ≥ 2 scale steps.
- Use generous whitespace when content density permits. Blank space is a composition problem, not a content-filling problem.

**Color**
- OKLCH for construction. Ramp recipe: hold hue + chroma, vary lightness; reduce chroma near white/black. Neutral ramp 9-11 steps, tinted 0.005-0.015 chroma toward THIS brand's hue — not reflex-warm or reflex-cool.
- Pick a **color strategy** before colors: **Restrained** (tinted neutrals + one accent ≤ 10% — product default) · **Committed** (one saturated color carries 30-60% — brand identity pages) · **Full palette** (3-4 named roles) · **Drenched** (the surface IS the color — campaign heroes).
- **Palette variation**: the warm cream/sand/beige body background is the saturated AI default. "Warm/artisan/editorial" briefs need not translate to a near-white warm bg — carry warmth via accent, typography, and imagery; pick a saturated brand color, a chroma-0 off-white, or a darker brand-tinted midtone instead.
- Dark vs light is never a default. Write one sentence of physical scene (who uses this, where, under what light, in what mood) — if the sentence doesn't force the answer, add detail until it does.
- Chroma tiers (low saturation reads premium): large backgrounds 0.01-0.04, brand/accent 0.08-0.15, small CTA pops 0.15-0.22.
- 60/30/10 as visual weight: 60% neutral/whitespace, 30% secondary, 10% accent. The accent works BECAUSE it is rare — never on inactive states.
- Pure black/white are valid brand choices; tinted neutrals are an alternative. Dark themes: tinted near-black at 12-18% L; elevate surfaces by lightening (3 steps ≈ 15/20/25% L, same hue), not by piling shadows.
- Contrast: ≥ 4.5:1 body (placeholders too), ≥ 3:1 large text and meaningful UI. Check gray text contrast on colored backgrounds; optionally — use a darker shade of the background's own hue. Muted text from the neutral ramp, not `opacity`. Heavy `rgba()` everywhere = incomplete palette; define explicit overlay colors.
- One gray family per page — never mix warm and cool grays. Sample palette hues from real brand assets/content imagery when they exist; write one sentence justifying the palette (can't write it = you're copying a recipe).

**Depth & surfaces**
- ONE depth strategy per surface — hairline borders, layered shadows, or surface-tint elevation. Mixing all three on one card is slop. The ghost-card combo (1px border + soft wide ≥16px-blur shadow) can muddy hierarchy; simplify if that happens.
- Shadows layered and tinted with the background hue: `0 1px 2px hsl(var(--shadow-hue) 30% 10% / 0.06), 0 4px 12px … / 0.08, 0 16px 32px … / 0.08`. Never the default gray `0 4px 8px rgba(0,0,0,0.1)`.
- **Shape lock**: one radius system per page — all-sharp (0), all-soft (8-16px), or all-pill. Cards top out at 16px; 24px+ on cards is the over-round tell. Nested radius = parent radius − parent padding.
- **Theme lock**: one theme per page. `bg-zinc-950` next to `bg-zinc-900` is fine; a light section sandwiched into a dark page is broken. Max one deliberate theme-switch device per page.

**Motion** (for scroll animation, GSAP, or `MOTION_INTENSITY > 4` builds, read `motion-craft.md` before implementing)
- The 100/300/500 rule: 100-150ms instant feedback (press, toggle) · 200-300ms state changes (hover, menu, tooltip) · 300-500ms layout changes (accordion, modal, drawer) · 500-800ms entrances (hero only). Exits run at ~75% of entrance duration.
- Easing tokens: `--ease-out-quart: cubic-bezier(0.25,1,0.5,1)` · `--ease-out-quint: cubic-bezier(0.22,1,0.36,1)` · `--ease-out-expo: cubic-bezier(0.16,1,0.3,1)`. Springs fine (`stiffness: 100, damping: 20`). Consider whether `linear`, bounce `cubic-bezier(0.34,1.56,0.64,1)` and elastic easings support the interaction; avoid disorienting effects.
- Stagger 30-60ms per item, total sequence ≤ 500ms; more items → shorter per-item delay.
- Animate only `transform`, `opacity`, `color`, `box-shadow` (grid-template-rows or FLIP for expansion; blur/clip-path allowed when bounded and verified smooth). Never `transition: all`. Never `width/height/top/left/margin`.
- **Reveal safety**: content must be visible by default; animation enhances it. Never gate visibility on a class-triggered transition (hidden tabs and headless renderers ship the section blank).
- The uniform whole-section fade-and-rise applied to every section is a tell. Stagger within one list is legitimate; each reveal should fit what it reveals. A static design is valid when motion would not help.
- Motion must be motivated by hierarchy, feedback, story, or state — "looked cool" is invalid. Product UI: state-conveying 150-250ms only, usually no load choreography. Pause ≥ 300ms before a key reveal (reaction time); end sequences with a hard stop, not a fade.
- Scroll tech: `useScroll`/`useMotionValue`/`ScrollTrigger`/`IntersectionObserver`/CSS `animation-timeline` — never raw scroll listeners or `useState` for continuous values. GSAP pins: `start: "top top"` (not `"top center"` — the #1 pin failure), `pin: true`; horizontal pan: `end: "+=" + (track.scrollWidth - innerWidth)`, `scrub: 1`, `invalidateOnRefresh: true`. Use a marquee only when it serves content, with pause and reduced-motion support.
- `@media (prefers-reduced-motion: reduce)` alternative for every animation. Non-negotiable.

**Interaction states**
- Every interactive element ships: default, hover, `:focus-visible`, active, disabled, loading, error/success where applicable. Focus ring: 2-3px, offset outside the element, ≥ 3:1 contrast, on-brand.
- Hover states move or reveal something (lift `translateY(-2px)`, underline slide, icon nudge) — not just a color dim. Press: `translateY(2px)` or `scale-[0.98]` at ~100ms.
- Touch targets ≥ 44×44px even when the visual is smaller (expand via `::before { inset: -10px }`).
- Dropdown clipping: use the Popover API, native `<dialog>`, or a portal + `position: fixed` — never `position: absolute` inside `overflow: hidden` (the single most common generated-code bug).
- Forms: validate on blur (not per keystroke), errors below the field with `aria-describedby`, placeholders are not labels. Skeletons > spinners. Undo > confirm (confirm only for irreversible/batch).
- Working-memory caps: ≤ 4 metrics above the fold, ≤ 5 top-level nav items, ≤ 4 fields per visual group, ≤ 3 pricing tiers, 1 primary button per view.

**Imagery & icons**
- Image-led briefs (restaurant, hotel, travel, fashion, product, photography) REQUIRE real imagery — CSS scenery, decorative gradient panels, or div-built fake screenshots/dashboards are broken implementations, not interpretations.
- Source order: generation tools → seeded placeholders (`https://picsum.photos/seed/{descriptive-keyword}/1600/900`) → labeled TODO slots. Verify real URLs before referencing (guessed photo IDs ship as broken images). Apply CSS treatment (grayscale, `contrast-125`, duotone, `mix-blend-luminosity`) so photos don't read as stock. One decisive photo > five mediocre.
- ONE icon family per project (Phosphor, Heroicons, Tabler — or the project's existing set), one stroke width (1.5 or 2.0). No emoji as icons. No hand-rolled "sketchy" SVG illustration scenes — no illustration beats bad illustration. Real brand logos via `https://cdn.simpleicons.org/{slug}`.

**Content & copy**
- Per section: headline ≤ 8 words, supporting text ≤ 25 words, one visual or CTA. Quotes ≤ 3 lines with name + role. Lists > 5 items need a different component (grouped columns, tabs, cards) — never a long `<ul>` with dividers.
- Realistic messy numbers (`$48,217`, `+7.3%`, `12,304 users`) — never fabricated stats presented as real, never fake-round (`10,000+ customers`, `99.99%`). An honest labeled placeholder beats an invented metric.
- Banned copy: "Elevate", "Seamless", "Unleash", "Empower", "Supercharge", "Next-Gen", "Game-changer". Banned furniture: scroll cues ("Scroll to explore"), version stamps (BETA / v1.4.2), fake photo credits, decorative status dots, locale/time/weather strips. Step labels are verb-nouns ("Install, Configure, Ship"), not "Stage 1/2/3".
- No em-dash (`—`) in visible UI copy — zero tolerance; it is the most reliable AI copy tell. Use a period, comma, or rewrite.
- Copy self-audit before shipping: re-read every visible string; rewrite anything grammatically broken, referent-less, or "trying to sound thoughtful". Plain and specific beats cute.

## Layout Discipline

**Hero**
- Fits the initial viewport (`min-h-[100dvh]`, never `h-screen`). Max 4 text elements: (eyebrow OR brand strip) + headline + subtext (≤ 20 words) + CTAs (1 primary + ≤ 1 secondary, labels ≤ 3 words).
- Banned inside the hero: trust micro-strips, avatar rows, pricing teasers, feature bullets, logo walls (own section below the fold), floating badge/stamp icons, pills overlaid on images, raw stat blocks.
- One CTA label per intent page-wide ("Get in touch" and "Let's talk" on one page = fail). Button text contrast always perfect: dark bg → white text, light bg → dark text.

**Section rhythm**
- **Eyebrow rationing**: the tiny uppercase-tracked kicker above a heading — max 1 per 3 sections, hero included. Countable check: `uppercase tracking` occurrences ≤ ceil(sections/3). Default fix: delete it; the headline is enough.
- Numbered section markers (01 / 02 / 03) only when the content IS a real ordered sequence. Meta-labels ("SECTION 01", "ABOUT US" as decoration) should be omitted when they carry no meaning.
- **Layout variation**: consider different families when content benefits; repeated patterns are useful for comparable content. No minimum diversity quota.
- Section vertical rhythm at low density: `py-24`–`py-48` desktop, roughly half on mobile. Sections read as distinct chapters.

**Grids & cards**
- Equal feature cards are appropriate for parallel content. For other content, consider alternatives. Use asymmetric fractions (`grid-template-columns: 2fr 1fr 1fr`), split-screens, masonry, or spacing-and-divider layouts.
- Bento grids: exactly N cells for N items — no blank filler tiles; `grid-auto-flow: dense` and verify col/row spans interlock with zero voids. 3-5 intentional cells beat 8 messy ones; use visual variation where the actual content warrants it; text-only cells are valid.
- Cards are the lazy default — use them only when they're truly the best affordance; never nest cards in cards. Breakpoint-free grids: `repeat(auto-fit, minmax(280px, 1fr))`.
- Nav: single line at desktop, 64-72px tall. Semantic z-index scale (dropdown → sticky → backdrop → modal → toast → tooltip); never `z-[9999]`.

## Common aesthetic pitfalls

The converged, medium-agnostic version of this list (for skills producing non-code design output — slides, posters, logos, banners, showcase pages) lives at `./references/design-quality-preflight.md`. This section stays the exhaustive, code-specific authority; keep new bans here, not duplicated there.

Review these common defaults for fit with the brief; retain them when requested or established by the brand:

- **Fonts**: Inter/Roboto/Arial/system-ui as display type. Burned-out AI-tell faces: Fraunces, Space Grotesk, Playfair Display, Instrument Serif (substitutes: Schibsted Grotesk, Archivo, Libre Caslon, Bodoni Moda). Never the same serif or palette family twice in a row across generations. Display fonts in labels, buttons, or data.
- **Color**: purple-gradient-on-white; raw `#000`/`#FFF`; oversaturated evenly-distributed palettes; cream/beige-by-default (see anti-cream rule); mixing warm and cool grays; full-saturation accents on inactive elements; flag-color palettes for cultural briefs.
- **Surfaces**: side-stripe borders (`border-left` > 1px as colored accent on cards/callouts); gradient text (`background-clip: text`); glassmorphism as default; ghost cards (1px border + wide soft shadow); over-rounding (24px+ card radius); `repeating-linear-gradient` stripe backgrounds; decorative grid-line backgrounds (unless the surface is literally a canvas/map/blueprint); neon outer glows; custom cursors (unless asked).
- **Layout**: centered hero + 3 equal cards template; hero-metric template (big number + label + stats + gradient); identical icon-heading-text card grids; eyebrow kicker on every section; numbered markers as scaffolding; `h-screen`; big rounded icon above every heading; split-header (huge left headline + small right paragraph).
- **Components**: default unstyled shadcn; mixed icon families; monospace as costume for "technical"; custom scrollbars and reinvented form controls; modal as the first thought in product UI.
- **Content**: "John Doe", "Acme Corp", lorem ipsum, round fake numbers, AI copy clichés, meta-labels, em-dashes in UI copy.

User and brand choices govern; do not replace them to satisfy a stylistic heuristic.
