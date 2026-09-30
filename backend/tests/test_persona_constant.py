"""The persona constant has exactly one canonical copy.

The personas admin page is gone, so the seed fixture and the graph fallback
must both carry ``DEFAULT_PERSONA_BODY_MD`` verbatim — a drift between them
would make a fresh dev seed speak with a different voice than a deployment
whose persona row is missing.
"""

from types import SimpleNamespace
from uuid import uuid4

from app.graph.prompts import AGENT_SYSTEM_PROMPT
from app.services.personas.constant import (
    DEFAULT_PERSONA_BODY_MD,
    DEFAULT_PERSONA_NAME,
    DEFAULT_PERSONA_SLUG,
)


def test_graph_fallback_is_the_canonical_constant():
    assert AGENT_SYSTEM_PROMPT == DEFAULT_PERSONA_BODY_MD.strip()


def test_seed_default_persona_is_the_canonical_constant():
    from scripts.seed.personas import make_personas

    default_row, inactive_row = make_personas([SimpleNamespace(id=uuid4())])

    assert default_row.body_md == DEFAULT_PERSONA_BODY_MD
    assert default_row.name == DEFAULT_PERSONA_NAME
    assert default_row.slug == DEFAULT_PERSONA_SLUG
    assert default_row.is_active is True
    # The inactive preset stays a distinct row: only the default carries the
    # canonical body.
    assert inactive_row.body_md != DEFAULT_PERSONA_BODY_MD
    assert inactive_row.is_active is False
