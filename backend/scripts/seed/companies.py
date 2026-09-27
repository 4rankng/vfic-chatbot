"""Company fixture: one factory operator per seeded project."""

from __future__ import annotations

from app.models.company import Company, Project

from .common import new_uuid


def make_companies(projects: list[Project]) -> list[Company]:
    """One company per project (the factory operator)."""
    companies = []
    for p in projects:
        companies.append(
            Company(id=new_uuid(), project_id=p.id, name=f"Cty TNHH {p.name}", aliases=[p.name]),
        )
    return companies
