"""Framework-free policies for the single installation authority."""

from app.installation.domain.projection import (
    contains_secret_key,
    contains_secret_value,
    project_public_mapping,
    project_public_terminology,
    secret_like_key,
)

__all__ = [
    "contains_secret_key",
    "contains_secret_value",
    "project_public_mapping",
    "project_public_terminology",
    "secret_like_key",
]
