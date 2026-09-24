"""Console resources must resolve to real backend routes.

Both suites are driven from one shared table,
``frontend/src/components/atomic-crm/providers/rest/resource-paths.json``:
the frontend test drives the real dataProvider against every entry, and this
test asserts each table is a GET route in the backend's OpenAPI schema. A
route rename or prefix move therefore breaks the contract test instead of
404-ing the console at runtime.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app as main_app

_TABLE = (
    Path(__file__).resolve().parents[2]
    / "frontend/src/components/atomic-crm/providers/rest/resource-paths.json"
)


def _load_table() -> dict[str, str]:
    raw = json.loads(_TABLE.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def test_every_console_resource_path_is_a_real_backend_get_route():
    fastapi_app = getattr(main_app, "other_asgi_app", main_app)
    paths = fastapi_app.openapi()["paths"]
    table = _load_table()
    assert len(table) >= 8, "the shared resource-path table must not silently shrink"

    for resource, segment in sorted(table.items()):
        url = f"/api/v1/{segment}"
        route_methods = paths.get(url)
        assert route_methods is not None, (
            f"frontend resource {resource!r} targets {url}, which the backend "
            "does not expose"
        )
        assert "get" in route_methods, f"{url} lost its list GET route"
