"""Compatibility re-exports for FastAPI dependency providers."""

from app.api.auth_dependencies import (
    get_current_user,
    get_user_from_token,
    oauth2_scheme,
    require_admin,
    require_recruiter,
)
from app.api.installation_dependencies import (
    get_active_installation,
    require_capability,
    require_capability_or_legacy,
)
from app.api.provider_dependencies import get_embedder
from app.core.db import get_db

__all__ = [
    "get_active_installation",
    "get_current_user",
    "get_db",
    "get_embedder",
    "get_user_from_token",
    "oauth2_scheme",
    "require_admin",
    "require_capability",
    "require_capability_or_legacy",
    "require_recruiter",
]
