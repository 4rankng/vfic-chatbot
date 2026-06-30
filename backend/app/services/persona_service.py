"""Backward-compat re-exports — import from app.services.personas instead."""

from app.services.personas import (  # noqa: F401
    PersonaService,
    load_persona_template,
    parse_persona_markdown,
)
