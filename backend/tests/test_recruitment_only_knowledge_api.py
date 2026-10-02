"""Public knowledge API is limited to recruitment KB releases and documents."""

from app.api import knowledge


def _relative_routes() -> set[tuple[str, str]]:
    return {
        (method, route.path.removeprefix("/knowledge"))
        for route in knowledge.router.routes
        for method in route.methods or set()
    }


def test_generic_template_and_structured_fact_routes_are_not_registered() -> None:
    routes = _relative_routes()

    assert {
        ("GET", "/ingestion-templates"),
        ("POST", "/ingestion-templates"),
        ("POST", "/ingestion-templates/preview"),
        ("GET", "/ingestion-template-starter-packs"),
        ("GET", "/ingestion-templates/{template_id}/versions"),
        ("POST", "/ingestion-templates/{template_id}/drafts"),
        ("PATCH", "/ingestion-template-versions/{version_id}"),
        ("POST", "/ingestion-template-versions/{version_id}/preview"),
        ("POST", "/ingestion-template-versions/{version_id}/publish"),
        ("POST", "/ingestion-template-versions/{version_id}/deprecate"),
        ("GET", "/projects/{project_id}/ingestion-template-assignment"),
        ("PUT", "/projects/{project_id}/ingestion-template-assignment"),
        ("GET", "/ingestion-runs/{run_id}"),
        ("POST", "/ingestion-runs/{run_id}/approve"),
        ("POST", "/ingestion-runs/{run_id}/reject"),
        ("GET", "/projects/{project_id}/kb/versions/{version_id}/ingestion-runs"),
        ("GET", "/projects/{project_id}/structured-facts"),
    }.isdisjoint(routes)



