# Example: Architecture Decision with Sequential Thinking

Use these illustrative domain records selectively. Report observable evidence, assumptions, alternatives and decisions; do not expose a private thought transcript or reproduce the numbering as a required protocol. Example facts are hypothetical, not evidence about the current project.
**Problem**: Choose state management for growing React app.

## Evidence and decision record

```
Record 1: Initial assessment

React app growing complex. useState scattered across components.
Need centralized state management.
Options: Redux, MobX, Zustand, Context API, Jotai.

Next: Define requirements

Record 2: Requirements (adjusted up)

App needs:
- Real-time updates (WebSocket)
- Offline support
- Complex nested state
- Multiple devs (maintainability)
- TypeScript (type safety)

These eliminate simpler solutions.
Next: Evaluate remaining options

Record 3 [REVISION of record 1]: Scope refinement

Original assumption: Need global state management.
Realization: Not all state needs centralization.

Better breakdown:
- Server state (API data): React Query
- UI state (modals, forms): Local useState
- Auth state: Context API
- App-wide settings: Simple global store

This reduces problem scope significantly.
Changes evaluation criteria.
Next: Re-evaluate with refined scope

Record 4: Re-evaluation (adjusted)

Only need lightweight store for app-wide settings.
Zustand fits:
- Minimal boilerplate
- Excellent TypeScript support
- No provider wrapper
- ~1KB size

React Query handles server state (caching, refetch, offline).
Most state stays local.

Next: Verify this handles all requirements

Record 5 [HYPOTHESIS]: Hybrid approach

Hypothesis: Zustand + React Query + local state solves needs.

- Zustand: Theme, user prefs, global UI flags
- React Query: All server data, caching, sync
- useState: Component-local UI

Benefits: Simple, performant, maintainable.
Uncertainty: Real-time updates?

Record 6 [FINAL]: Verified solution

React Query supports WebSocket via custom hooks.
Zustand handles global UI simply.
Local state for component-specific needs.

Architecture decision:
- Zustand for global UI state
- React Query for all server interactions
- Local useState for component state

Confidence: High
Assumptions: Team comfortable with React Query patterns
Benefits: Simpler than Redux, more powerful than Context
Trade-offs: Learning curve for React Query (but worthwhile)
```

## Key Insights

1. **Scope revision crucial**: Original "need global state" reframed to specific state categories
2. **Separation of concerns**: Different state types need different solutions
3. **Hypothesis verification**: Confirmed WebSocket support before finalizing
4. **Simpler is better**: Avoided over-engineering with heavy Redux solution

## Impact of Revision

Without record 3 revision, might have chosen Redux for all state—significant over-engineering. Revision led to more appropriate, simpler solution.
