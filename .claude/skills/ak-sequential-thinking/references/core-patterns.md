# Core Sequential Thinking Patterns

Use these illustrative domain records selectively. Report observable evidence, assumptions, alternatives and decisions; do not expose a private thought transcript or reproduce the numbering as a required protocol. Example facts are hypothetical, not evidence about the current project.
Essential revision and branching patterns.

## Revision Patterns

### Assumption Challenge
Early assumption proves invalid with new data.
```
Record 1: Assume X is bottleneck
Record 4 [REVISION of record 1]: X adequate; Y is actual bottleneck
```

### Scope Expansion
Problem larger than initially understood.
```
Record 1: Fix bug
Record 4 [REVISION of scope]: Architectural redesign needed, not patch
```

### Approach Shift
Initial strategy inadequate for requirements.
```
Record 2: Optimize query
Record 5 [REVISION of record 2]: Optimization + cache layer required
```

### Understanding Deepening
Later insight fundamentally changes interpretation.
```
Record 1: Feature broken
Record 4 [REVISION of record 1]: Not bug—UX confusion issue
```

## Branching Patterns

### Trade-off Evaluation
Compare approaches with different trade-offs.
```
Record 3: Choose between X and Y
Record 4 [BRANCH A]: X—simpler, less scalable
Record 4 [BRANCH B]: Y—complex, scales better
Record 5: Choose Y for long-term needs
```

### Risk Mitigation
Prepare backup for high-risk primary approach.
```
Record 2: Primary: API integration
Record 3 [BRANCH A]: API details
Record 3 [BRANCH B]: Fallback: webhook
Record 4: Implement A with B contingency
```

### Parallel Exploration
Investigate independent concerns separately.
```
Record 3: Two unknowns—DB schema & API design
Record 4 [BRANCH DB]: DB options
Record 4 [BRANCH API]: API patterns
Record 5: Integrate findings
```

### Hypothesis Testing
Test multiple explanations systematically.
```
Record 2: Could be A, B, or C
Record 3 [BRANCH A]: Test A—not cause
Record 3 [BRANCH B]: Test B—confirmed
Record 4: Root cause via Branch B
```

## Adjustment Guidelines

**Expand when**: Complexity discovered, multiple aspects identified, verification needed, alternatives require exploration.

**Contract when**: Key insight solves earlier, problem simpler, steps merge naturally.

**Example**:
```
Record 1: Initial
Record 3: Complexity (5→7)
Record 5: Another aspect (7→8)
Record 8 [FINAL]: Complete
```

## Anti-Patterns

**Premature Completion**: Rushing without verification → Add verification thoughts.

**Revision Cascade**: Repeated revisions without understanding why → Identify root cause.

**Branching Explosion**: Too many branches → Limit to 2-3, converge before more.

**Context Loss**: Ignoring earlier insights → Reference previous thoughts explicitly.
