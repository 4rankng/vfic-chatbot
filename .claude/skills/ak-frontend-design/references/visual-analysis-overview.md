# Visual Analysis Overview

Use AI multimodal vision to analyze generated assets and verify design standards.

## Purpose

- Verify generated assets align with aesthetic direction
- Ensure professional quality before integration
- Identify specific improvements needed for iteration
- Make objective design decisions based on analysis
- Extract actionable data (hex codes, composition insights)

## Quick Start

### Comprehensive Analysis
```bash
npx -y -p @mrgoonie/multix@0.2.0 multix gemini analyze \
  --files docs/assets/generated-hero.png \
  --prompt "[see analysis-prompts.md for detailed prompt]" \
  --output docs/assets/analysis-report.md \
  --model gemini-2.5-flash
```

### Compare Multiple Variations
```bash
npx -y -p @mrgoonie/multix@0.2.0 multix gemini analyze \
  --files docs/assets/option-1.png docs/assets/option-2.png docs/assets/option-3.png \
  --prompt "[see analysis-prompts.md for comparison prompt]" \
  --output docs/assets/comparison-analysis.md \
  --model gemini-2.5-flash
```

### Extract Color Palette
```bash
npx -y -p @mrgoonie/multix@0.2.0 multix gemini analyze \
  --files docs/assets/final-asset.png \
  --prompt "Extract 5-8 dominant colors with hex codes. Classify as primary/accent/neutral. Suggest CSS variable names." \
  --output docs/assets/color-palette.md \
  --model gemini-2.5-flash
```

## Decision framework

- When the asset meets the brief, has adequate resolution, and integrates without legibility or visual defects, optimize and integrate it.
- For a specific defect, repair or regenerate that area and check the result again.
- For a mismatch to the requested content or brand, revise the prompt or select another asset. A low subjective score alone does not require generation, and a high score does not excuse a concrete defect.

Use native vision when available; provider commands above are optional alternatives requiring the user's authorized provider setup. Do not force multiple generations or reports for an already-suitable asset.

## Before Finishing

Once the asset is integrated into the frontend build,
run the handoff gate in `../../ak-design/references/handoff-gate.md` before
presenting the result as done: fix each failing dimension, or list it under
"Known limitations" in the handoff template — never ship a known failure
silently.

## Detailed References

- `analysis-prompts.md` - All analysis prompt templates
- `analysis-techniques.md` - Advanced analysis strategies
- `analysis-best-practices.md` - Quality guidelines and pitfalls

## Example Color Extraction Output

```css
/* Extracted Color Palette */
:root {
  /* Primary Colors */
  --color-primary-600: #2C5F7D;  /* Dark teal - headers, CTAs */
  --color-primary-400: #4A90B8;  /* Medium teal - links, accents */

  /* Accent Colors */
  --color-accent-500: #E8B44F;   /* Warm gold - highlights */

  /* Neutral Colors */
  --color-neutral-900: #1A1A1A;  /* Near black - body text */
  --color-neutral-100: #F5F5F5;  /* Light gray - backgrounds */

  /* Semantic Usage */
  --color-text-primary: var(--color-neutral-900);
  --color-text-on-primary: #FFFFFF;
  --color-background: var(--color-neutral-100);
  --color-cta: var(--color-primary-600);
}
```
