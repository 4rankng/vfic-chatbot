"""Persona package — CRUD + activate + template import.

Public API re-exported here; importers should depend on ``app.services.personas`` rather
than the internal submodules. ``PersonaService`` and ``load_persona_template`` live in
``service.py``; ``parse_persona_markdown`` lives in ``parsing.py``; raw DB access lives
behind :class:`PersonaRepository` in ``repository.py``.
"""

from __future__ import annotations

from app.services.personas.parsing import parse_persona_markdown  # noqa: F401
from app.services.personas.service import PersonaService, load_persona_template  # noqa: F401
