"""Neutral prompt-templates package — no imports from ``graph`` or ``services``.

Prompts that are shared across layers live here so dependents import DOWNWARD only,
never from a higher layer. (The lead/memory prompts were previously in
``app.graph.lead_memory_prompts`` and imported UPWARD by ``services.lead_service`` /
``services.memory_service`` — a layering violation this package fixes.)
"""
from __future__ import annotations
