"""Canonical knowledge format identifiers owned by the domain."""

SCHEMA_VERSION = "vfic-knowledge-v1"
FAQ_SCHEMA_VERSION = "vfic-faq-v1"
CANONICAL_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION, FAQ_SCHEMA_VERSION})

__all__ = ["CANONICAL_SCHEMA_VERSIONS", "FAQ_SCHEMA_VERSION", "SCHEMA_VERSION"]
