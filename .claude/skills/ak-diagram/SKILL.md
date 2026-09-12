---
name: ak:diagram
description: >-
  Compile typed JSON IR into validated interactive system maps and self-contained
  HTML readers. Use for architecture, workflow, sequence, dataflow and lifecycle
  maps; use editable-canvas or publication-diagram skills for those artifacts.
user-invocable: true
when_to_use: >-
  Choose ak:diagram when the desired artifact is a validated interactive system map,
  typed JSON IR diagram, or self-contained HTML reader with grounded graph queries. Route to
  ak:excalidraw for whiteboard sketches, ak:tech-graph for static publication charts, or
  ak:mermaidjs-v11 for inline markdown diagrams.
category: dev-tools
keywords: [diagram, archify, architecture, workflow, sequence, dataflow, lifecycle, interactive-map, system-map, visual-map, reader-runtime]
argument-hint: "[input-file] [--format <svg|fragment|html>] [--preset <classic|signal-flow|blueprint|editorial>] [--theme <light|dark>] [--out <path>]"
license: MIT
metadata:
  author: agentkit
  version: "2.1.1"
  upstream_templates: cathrynlavery/diagram-design (MIT)
  upstream_compiler: tt-a1i/archify v2.16.0 (MIT, commit c826e6c3a7abad19c0f3cd1ca57207d54b1ad8de)
  vendored_mermaid_version: "11.4.1"
---

# ak:diagram — Unified System Map & Interactive Diagram Surface

Compile typed JSON IR specifications into deterministic SVGs, embeddable fragments, and self-contained interactive HTML readers without browser dependencies.

## Archetype Decision Matrix

| User Intent | Archetype | Primary Entities | Key Fields |
|---|---|---|---|
| System topology, microservices, boundaries | `architecture` | `components`, `boundaries`, `connections` | `role`, `layer` (0–10), `kind` |
| Multi-step execution, lane handoffs, decisions | `workflow` | `lanes`, `steps`, `transitions` | `kind`, `lane`, `condition` |
| Ordered API calls, request/response timing | `sequence` | `participants`, `messages` | `kind: sync-call \| return` |
| ETL pipelines, stream processing, data lineage | `dataflow` | `stages`, `nodes`, `flows` | `stage`, `role`, `classification` |
| Finite state machines, status transitions | `lifecycle` | `states`, `transitions`, `lanes` | `kind: initial \| active \| ...` |

## 5-Step Execution Playbook

1. **Select Archetype**: Match user intent to one of the 5 archetypes above.
2. **Author Typed JSON IR**:
   - Set envelope: `{"schema_version": 1, "diagram_type": "<type>", "meta": {...}}`.
   - Set visual preset: `classic` (clean slate), `signal-flow` (emerald/cyan glow), `blueprint` (technical dark blue), or `editorial` (warm serif).
   - Set theme: `light` or `dark`. For finite motion, set `animation: "trace"` ($\le 8\text{s}$).
   - Optional guided story: add `meta.views: [{"id": "ch1", "title": "...", "narrative": "...", "focus_nodes": [...]}]` (max 5 chapters).
3. **Apply Schema Invariants**:
   - Use strict role enums on nodes (compiler validates node roles at compile time).
   - Keep IDs alphanumeric + hyphens (`^[a-zA-Z0-9_-]{1,64}$`).
   - For `workflow`, ensure lane names have adequate horizontal space (`currentX >= 240`).
4. **Compile Offline (Zero Browser)**:
   ```bash
   node scripts/compiler/compile.mjs --input diagram.json --format html --out ./build/diagram.html --preset signal-flow --theme dark
   node scripts/compiler/compile.mjs --input diagram.json --format svg --out ./build/diagram.svg --preset signal-flow --theme dark
   ```
5. **Deliver & Embed**: Deliver the self-contained `.html` (interactive reader with keyboard shortcuts) or clean vector `.svg`.

## Schema Cheat Sheet & Valid Enums

Load `references/schema-and-reader.md` only for this part of the task.

## Common Commands

```bash
# Compile typed IR to standalone interactive HTML reader
node scripts/compiler/compile.mjs --input diagram.json --format html --out ./build/diagram.html

# Compile typed IR to clean vector SVG
node scripts/compiler/compile.mjs --input diagram.json --format svg --out ./build/diagram.svg

# Compile to embeddable scoped HTML fragment
node scripts/compiler/compile.mjs --input diagram.json --format fragment --preset signal-flow --theme dark

# Legacy Python wrapper (auto-detects typed IR vs Mermaid vs legacy template)
python3 scripts/render.py --input diagram.json --out ./build/
```

## Security & Boundaries

- **Zero Network**: Compilation operates offline in pure Node.js; no remote calls, telemetry, or font downloads.
- **Deterministic**: Compiling identical IR bytes emits identical SHA-256 output bytes across environments.
- **Finite Motion**: All animations are finite ($\le 8\text{s}$) and automatically disabled under `prefers-reduced-motion: reduce`.
- **Scope Limit**: For freeform whiteboard sketching, use `ak:excalidraw`. For static print infographics, use `ak:tech-graph`. For raw markdown inline doc blocks, use `ak:mermaidjs-v11`.
