# Analysis Best Practices

Quality guidelines and common pitfalls.

## Analysis Best Practices

### 1. Be Specific
❌ Generic: "Is this image good?"
✓ Specific: "Does this align with brutalist aesthetic? Rate text overlay suitability."

### 2. Use Structured Prompts
Format analysis requests with numbered criteria for actionable feedback:
```
1. [Criterion A]
2. [Criterion B]
3. [Criterion C]
Observed defects / acceptance criteria met / unverified areas
```

### 3. Request Hex Codes
❌ Accept: "The image uses blue tones"
✓ Demand: "Extract hex codes: #1E40AF, #3B82F6, #60A5FA"

### 4. Compare Variations
Compare variations when the brief calls for exploration or the first asset misses its criteria. Generate only useful alternatives and select against observed suitability.

### 5. Test Integration Context
Analyze assets *with* UI elements overlaid, not in isolation:
- Mock up text overlays
- Test with actual buttons and CTAs
- Evaluate in responsive contexts

### 6. Document Decisions
Save analysis only when the decision is durable or the user requests a report; this is an optional layout:
```
docs/
  assets/
    hero-image.png
    hero-analysis.md       # Analysis report
    hero-color-palette.md  # Extracted colors
  design-guidelines/
    asset-usage.md         # Guidelines derived from analysis
```

## Common Analysis Pitfalls

### ❌ Vague Feedback
Analysis returns: "Colors are nice"
**Fix**: Request specific hex codes and harmony evaluation

### ❌ Unsupported Approval
Analysis returns: "Pretty good quality"
**Fix**: Request concrete evidence of resolution, legibility, brand fit and integration. An optional score is not a pass gate.

### ❌ Missing Context
Analyzing asset without specifying intended use
**Fix**: Include context in prompt (hero section, background, marketing, etc.)

### ❌ Single Analysis Point
Only checking aesthetic, ignoring technical or integration concerns
**Fix**: Use comprehensive evaluation template covering all dimensions

## Evaluation Criteria

### Core Evaluation Points
- Visual coherence with chosen aesthetic direction
- Color harmony and palette consistency
- Composition balance and focal points
- Typography compatibility (if text overlay needed)
- Observable visual defects and fit to the brief
- Technical suitability (aspect ratio, resolution, file characteristics)

### Context-Specific Points
- **For hero sections**: Suitability for text overlay, visual hierarchy support
- **For backgrounds**: Subtlety, pattern repetition quality, texture detail
- **For marketing**: Brand alignment, emotional impact, attention-grabbing power
- **For decorative elements**: Integration potential, visual weight, uniqueness
