"""VFIC chatbot prompts.

The agent persona is a code constant — ``app.prompts.vfic_persona`` — owned by
this repository, not operator-editable content. The personas admin page was
removed on 2026-09-30 and persona storage was removed on 2026-10-04, so this is
not a fallback any more: ``AGENT_SYSTEM_PROMPT`` *is* the persona every lane
speaks, and there is no database copy that could drift from it.

The body lives in the neutral ``app.prompts`` layer because this graph runtime
module may not import a concrete service module
(``tests/test_graph_import_guard.py``).
"""

from app.prompts.vfic_persona import DEFAULT_PERSONA_BODY_MD

AGENT_SYSTEM_PROMPT = DEFAULT_PERSONA_BODY_MD.strip()
