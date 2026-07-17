"""Transport guards for standalone knowledge-base administration."""

from __future__ import annotations

from app.api import knowledge_bases
from app.api.dependencies import require_admin


def test_every_knowledge_base_route_requires_admin() -> None:
    assert knowledge_bases.router.routes
    for route in knowledge_bases.router.routes:
        assert any(
            dependency.call is require_admin for dependency in route.dependant.dependencies
        ), route.path


def test_bootstrap_route_is_registered_before_id_routes() -> None:
    paths = [route.path for route in knowledge_bases.router.routes]
    assert paths.index("/knowledge-bases/bootstrap-legacy") < paths.index(
        "/knowledge-bases/{knowledge_base_id}"
    )
