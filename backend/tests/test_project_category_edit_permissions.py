"""Authorization wiring for manual project-category editing."""

from __future__ import annotations

import inspect

from fastapi.params import Depends

from app.api.auth_dependencies import require_recruiter
from app.api.projects import replace_project_category


def test_manual_category_replacement_allows_admins_and_recruiters() -> None:
    dependency = inspect.signature(replace_project_category).parameters["editor"].default

    assert isinstance(dependency, Depends)
    assert dependency.dependency is require_recruiter
