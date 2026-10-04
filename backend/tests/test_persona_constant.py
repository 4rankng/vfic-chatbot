"""The persona constant has exactly one canonical copy, and it is the only copy.

Persona storage was removed on 2026-10-04: the ``personas`` table, the persona
service and the seed fixture are gone, so ``DEFAULT_PERSONA_BODY_MD`` is not a
"canonical" copy that other holders must track — it is the persona. This test
exists to keep the two module-level aliases pointing at the same text, because
``app.graph.prompts`` re-exports it and a divergence there would mean one lane
speaking a different voice from another.
"""

from app.graph.prompts import AGENT_SYSTEM_PROMPT
from app.prompts.vfic_persona import DEFAULT_PERSONA_BODY_MD


def test_graph_fallback_is_the_canonical_constant():
    assert AGENT_SYSTEM_PROMPT == DEFAULT_PERSONA_BODY_MD.strip()


def test_no_database_persona_module_remains():
    """The persona is code-only: the storage layer must not creep back in.

    A re-added ``app.models.persona`` would be inert, but it would also restore
    the illusion that the persona lives somewhere a deploy does not reach — the
    exact drift that made the previous production persona uneditable.
    """
    import importlib.util

    assert importlib.util.find_spec("app.models.persona") is None
    assert importlib.util.find_spec("app.services.personas") is None
    assert importlib.util.find_spec("app.schemas.personas") is None
    assert importlib.util.find_spec("app.api.personas") is None


def test_the_manifest_checksum_hashes_the_same_persona_the_graph_speaks():
    """The installation lane and the graph must not disagree about the persona.

    The manifest service cannot import ``app.graph.prompts`` (a service slice may
    not reach outward into the graph — ``tests/test_architecture_boundaries.py``),
    so it hashes the neutral ``DEFAULT_PERSONA_BODY_MD`` directly. That only works
    while the graph's ``AGENT_SYSTEM_PROMPT`` is the same text: if one gained a
    wrapper or a transform, the manifest would pin a persona the bot never speaks,
    and nothing else in the suite would notice.
    """
    from app.services.installation.validation import current_persona_checksum
    from app.services.installation.hashing import sha256_json

    assert current_persona_checksum() == sha256_json({"body_md": AGENT_SYSTEM_PROMPT})
