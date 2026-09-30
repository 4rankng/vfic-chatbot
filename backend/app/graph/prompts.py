"""VFIC chatbot prompts.

The agent persona is a code constant — ``app.prompts.vfic_persona``, re-exported
by ``app.services.personas.constant`` — owned by this repository, not by
operator-editable content (the personas admin page was removed on 2026-09-30).
``AGENT_SYSTEM_PROMPT`` is the fallback body used when no DB persona row is
active; the seed fixture writes the same body into the ``personas`` table. The
body lives in the neutral ``app.prompts`` layer because this graph runtime module
may not import a concrete service module (``tests/test_graph_import_guard.py``).
"""

from app.prompts.vfic_persona import DEFAULT_PERSONA_BODY_MD

AGENT_SYSTEM_PROMPT = DEFAULT_PERSONA_BODY_MD.strip()
