"""Static inventory gate for routes, queued work, outbox, and provider I/O.

Later authority-stamp work must update this explicit migration oracle whenever a
new producer or dispatch boundary is added.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

APP_DIR = Path(__file__).parents[1] / "app"
FIXTURE = Path(__file__).parent / "fixtures" / "universal_platform"

ROUTE_MODULE_CLASSIFICATION = {
    "auth": "auth_setup",
    "users": "auth_setup",
    "conversations": "active_kernel",
    "leads": "capability.recruitment",
    "bot_runs": "active_kernel",
    "knowledge": "capability.knowledge",
    "knowledge_bases": "capability.knowledge",
    "projects": "capability.recruitment",
    "personas": "auth_setup",
    "jobs": "capability.recruitment",
    "dashboard": "capability.recruitment",
    "performance": "active_kernel",
    "integrations": "auth_setup",
    "installation": "auth_setup",
    "webhooks": "capability.channel.zalo",
}
DIRECT_ROUTE_CLASSIFICATION = {
    "/health": "public_ops",
    "/metrics": "public_ops",
    "/health/queue": "public_ops",
}
EXPECTED_ROUTE_COUNTS = {
    # Endpoint-level snapshot: adding a decorator inside an existing module must
    # fail this gate and force an explicit authority-classification review.
    "auth": 6,
    "bot_runs": 2,
    "conversations": 18,
    "dashboard": 2,
    "integrations": 20,  # Phase 4: +7 Facebook OAuth lifecycle endpoints
    # Meta App credentials UI: +2 (GET/PUT /facebook/credentials)
    "installation": 8,
    "jobs": 7,
    "knowledge": 25,  # +4 external-source-sync endpoints (list / create / run-now / delete)
    "knowledge_bases": 11,
    "leads": 15,
    "main": 3,
    "performance": 2,
    "personas": 11,  # adapter assignment GET/PUT replace project bulk assignment
    "projects": 28,  # +4 single-page external-source-sync endpoints
    "users": 10,
    "webhooks": 4,  # Phase 5: +2 Facebook webhook routes (GET challenge + POST events)
}
EXPECTED_ROUTE_INVENTORY_SHA256 = "3fecf58e9c1f3e94b0b692db4564e8e1cef6d94f57c7a5143adf09ae39737fec"
EXPECTED_BROAD_BOUNDARY_COUNTS = {
    # Recovery dispatch moved behind the conversation/messaging application port.
    "outbox_boundary": 9,
    "provider_boundary": 75,  # identity lookup moved behind an infrastructure gateway
    # Three service-owned worker calls moved behind the project/knowledge
    # application scheduler port; queue names and durable worker paths are unchanged.
    # +1 queue_producer: single-page sheet sync now enqueues direct-context indexing
    # so sheet-sourced DIRECT_CONTEXT content participates in cross-project retrieval.
    # OA profile enrichment moved from the compatibility service to composition,
    # removing one service-owned worker edge.
    "queue_producer": 32,
}
EXPECTED_BROAD_BOUNDARY_SHA256 = "dd909b443433e9b8d084d945dfff6b3f7f6c0b70fa0d9c3f62dddbeed6e81ab1"
CALL_CATEGORIES = {
    "queue_producer": {
        "enqueue",
        "enqueue_job",
        "enqueue_chat_run",
        "enqueue_persist_candidate",
        "enqueue_enrich_oa_profile",
        "enqueue_followup",
        "enqueue_ingest",
        "enqueue_ingest_version",
    },
    "outbox_boundary": {
        "enqueue_outbox",
        "create_pending_outbox",
        "dispatch_outbox",
        "dispatch_message_outbox",
    },
    "provider_boundary": {"send_message", "send_chat_action", "send_payload"},
}


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


class _CallInventory(ast.NodeVisitor):
    def __init__(self, relative_path: str, *, provider_transport: bool) -> None:
        self.relative_path = relative_path
        self.provider_transport = provider_transport
        self.scope: list[str] = []
        self.items: list[tuple[str, str, str, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        for category, names in CALL_CATEGORIES.items():
            if name in names:
                self.items.append(
                    (category, self.relative_path, ".".join(self.scope) or "<module>", name)
                )
                break
        self.generic_visit(node)


class _BroadCallInventory(_CallInventory):
    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        categories: list[str] = []
        if name:
            if "outbox" in name and name.startswith(("create", "enqueue", "dispatch")):
                categories.append("outbox_boundary")
            elif "enqueue" in name:
                categories.append("queue_producer")
            if name.startswith("send_") or (
                self.provider_transport
                and name
                in {"get", "getdel", "post", "put", "patch", "delete", "request"}
            ):
                categories.append("provider_boundary")
        for category in categories:
            self.items.append(
                (category, self.relative_path, ".".join(self.scope) or "<module>", name)
            )
        self.generic_visit(node)


def _included_router_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "include_router" or not node.args:
            continue
        router = node.args[0]
        if isinstance(router, ast.Attribute) and isinstance(router.value, ast.Name):
            modules.add(router.value.id)
    return modules


def _direct_routes(tree: ast.AST) -> set[str]:
    return {record[1] for record in _decorated_routes(tree)}


def _decorated_routes(tree: ast.AST) -> list[tuple[str, str, str, str]]:
    routes: list[tuple[str, str, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            if decorator.func.attr not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                continue
            router_name = (
                decorator.func.value.id
                if isinstance(decorator.func.value, ast.Name)
                else "<unknown>"
            )
            routes.append(
                (decorator.func.attr.upper(), str(decorator.args[0].value), node.name, router_name)
            )
    return routes


def _router_prefixes(tree: ast.AST) -> dict[str, str]:
    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if (
            not isinstance(node.value.func, ast.Name)
            or node.value.func.id != "APIRouter"
            or len(node.targets) != 1
            or not isinstance(node.targets[0], ast.Name)
        ):
            continue
        prefix = ""
        for keyword in node.value.keywords:
            if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant):
                prefix = str(keyword.value.value)
        prefixes[node.targets[0].id] = prefix
    return prefixes


def _route_records() -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for module, category in ROUTE_MODULE_CLASSIFICATION.items():
        tree = ast.parse((APP_DIR / "api" / f"{module}.py").read_text(encoding="utf-8"))
        prefixes = _router_prefixes(tree)
        api_prefix = "" if module == "webhooks" else "/api/v1"
        for method, path, function, router_name in _decorated_routes(tree):
            records.append(
                {
                    "module": module,
                    "method": method,
                    "path": f"{api_prefix}{prefixes.get(router_name, '')}{path}",
                    "function": function,
                    "classification": category,
                }
            )
    main_tree = ast.parse((APP_DIR / "main.py").read_text(encoding="utf-8"))
    for method, path, function, _router_name in _decorated_routes(main_tree):
        if path in DIRECT_ROUTE_CLASSIFICATION:
            records.append(
                {
                    "module": "main",
                    "method": method,
                    "path": path,
                    "function": function,
                    "classification": DIRECT_ROUTE_CLASSIFICATION[path],
                }
            )
    return sorted(records, key=lambda item: (item["path"], item["method"], item["function"]))


def _runtime_calls(*, broad: bool = False) -> list[dict]:
    counter: Counter[tuple[str, str, str, str]] = Counter()
    for path in sorted(APP_DIR.rglob("*.py")):
        if not any(part in {"api", "services", "workers", "graph"} for part in path.parts):
            continue
        relative_path = path.relative_to(APP_DIR.parent).as_posix()
        source = path.read_text(encoding="utf-8")
        provider_transport = any(
            marker in source for marker in ("get_http_client", "import httpx", "from httpx")
        ) or relative_path.endswith("api/integrations.py")
        visitor_type = _BroadCallInventory if broad else _CallInventory
        visitor = visitor_type(relative_path, provider_transport=provider_transport)
        visitor.visit(ast.parse(source))
        counter.update(visitor.items)
    return [
        {"category": category, "file": file, "scope": scope, "call": call, "count": count}
        for (category, file, scope, call), count in sorted(counter.items())
    ]


def test_every_registered_router_and_direct_route_has_an_authority_classification():
    main_tree = ast.parse((APP_DIR / "main.py").read_text(encoding="utf-8"))

    assert _included_router_modules(main_tree) == set(ROUTE_MODULE_CLASSIFICATION)
    assert _direct_routes(main_tree) == set(DIRECT_ROUTE_CLASSIFICATION)


def test_every_classified_router_contains_at_least_one_http_route():
    for module in ROUTE_MODULE_CLASSIFICATION:
        tree = ast.parse((APP_DIR / "api" / f"{module}.py").read_text(encoding="utf-8"))
        assert _direct_routes(tree), f"{module} has no inventoried route"


def test_every_http_endpoint_matches_the_reviewed_authority_snapshot():
    records = _route_records()
    counts = Counter(record["module"] for record in records)
    digest = hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert dict(sorted(counts.items())) == EXPECTED_ROUTE_COUNTS
    assert digest == EXPECTED_ROUTE_INVENTORY_SHA256
    assert all(
        record["classification"] in {"public_ops", "auth_setup", "active_kernel"}
        or record["classification"].startswith("capability.")
        for record in records
    )


def test_queue_outbox_and_provider_boundaries_match_the_explicit_inventory():
    expected = json.loads((FIXTURE / "runtime_surface_inventory.json").read_text(encoding="utf-8"))
    actual = _runtime_calls()

    assert actual == expected
    assert {item["category"] for item in actual} == set(CALL_CATEGORIES)


def test_broad_side_effect_scan_matches_reviewed_boundary_snapshot():
    actual = _runtime_calls(broad=True)
    counts = Counter(item["category"] for item in actual)
    digest = hashlib.sha256(
        json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert dict(sorted(counts.items())) == EXPECTED_BROAD_BOUNDARY_COUNTS
    assert digest == EXPECTED_BROAD_BOUNDARY_SHA256
