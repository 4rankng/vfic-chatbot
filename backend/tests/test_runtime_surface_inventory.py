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
    "auth": 7,  # +1 server-side logout (SEC-03)
    "bot_runs": 2,
    "conversations": 19,
    "dashboard": 2,
    "integrations": 34,  # +3 custom OpenAI-compatible provider endpoints (settings page); +3 Jev decision-model endpoints
    # +2 the TingTing support OA: save-and-check the four credentials (PUT /tingting)
    # and a re-probe endpoint (POST /tingting/oa/check)
    # +2 deployment-wide TingTing app API key (GET / PUT, secrets status-only)
    # +2 Meta App credentials UI; +4 multi-Page per-Page project CRUD
    # +1 admin-only credentials reveal (audited, no-store)
    "installation": 8,
    "jobs": 7,
    "knowledge": 25,  # +4 external-source-sync endpoints (list / create / run-now / delete)
    "knowledge_bases": 11,
    "leads": 15,
    "main": 3,
    "performance": 2,
    "personas": 11,  # adapter assignment GET/PUT replace project bulk assignment
    # +4 single-page external-source-sync endpoints
    # +2 project external-API endpoints (get / put)
    # +1 project external-API admin test-call endpoint (post)
    "projects": 28,
    "users": 10,
    "webhooks": 4,  # Phase 5: +2 Facebook webhook routes (GET challenge + POST events)
}
EXPECTED_ROUTE_INVENTORY_SHA256 = "cc5354340f429fbad2427a868840b286474fc72cf840e68991b45b63aced019f"
EXPECTED_BROAD_BOUNDARY_COUNTS = {
    # Scan the complete application tree so composition roots and bounded-context
    # adapters remain covered after transport logic moves out of legacy packages.
    "outbox_boundary": 10,
    # Same 10 sites; the claim_send / record_bot_outcome rows moved from
    # bot_path.py into send_claim.py / bot_outcome.py when the bot-send state
    # layer was split by change reason (file/scope keys only).
    # +2 for the Messenger User Profile API lookup (the Graph GET in
    # facebook_oauth.get_user_profile and the worker that calls it).
    # +7: the custom OpenAI-compatible probe + admin settings path; -2: the
    # degradation send left chatbot_worker (a suppressed turn sends nothing).
    # +3: the probe now reads finish_reason/usage and the reasoning-content
    # field so a reasoning model is not reported as a broken endpoint.
    # Same call site, second call: a version-less 404 base is retried once
    # with /v1 inserted (same host, same payload) — bumps the site's count
    # 1→2 without adding a distinct site.
    # Same site again: the OA user-detail error branch reads envelope.message
    # to tell a dead follower (-201 naming user_id) from a request bug —
    # bumps get_user_detail's get count 3→4, no new site.
    # +4: the gender judgment adds four dict `.get` lookups in
    # decisions.decide_turn (answers.get("gender"), the nested .get("choice"),
    # the confidence read, and answers.get("gender_stated")).
    # decisions.py carries get_http_client, so the provider_transport heuristic
    # counts every `.get` — dict reads included.
    # +1: decisions._retry_after_seconds reads two Retry-After headers with
    # `.get`; the heuristic counts the site once (rows are per (file, scope,
    # call), not per occurrence).
    # Same site, different verb: the OA refresh lock release became a Redis Lua
    # compare-and-delete (`eval`) instead of a blind `delete` (REL-03), so
    # integration_settings.refresh_oa_access_token contributes `eval` where it
    # used to contribute `delete` — one reviewed site either way, which is why
    # `eval` is in the scanned verb set.
    # +1: the OA sender's -201 unreachable classifier reads envelope.error /
    # envelope.message in zalo_oa_service._is_user_unreachable — one new
    # provider-transport `.get` site beside the existing result parsers.
    # +1: the Bot platform's send-result classifier
    # (zalo_bot_service._is_user_unreachable) reads the same error envelope
    # fields to tell a permanently invalid recipient (`user_id is invalid`) from
    # a transient failure — the bot-channel twin of the OA site above, and the
    # gate for the terminal-recipient mark.
    # +1: the answer-completion guard added clients._answer_was_cut, which reads
    # the provider response metadata (`finish_reason` / `stop_reason`) to tell a
    # generation cut at the output cap from a finished one. clients.py is a
    # provider-transport file, so both reads land in one reviewed row.
    # +1: the per-project external API integration opens one egress site in
    # app/services/project/external_api.py (ProjectExternalApiService._send's
    # single `client.request`). The module imports `get_http_client`, so the
    # whole file is classified provider transport; keeping the outbound call in
    # one private method is what keeps this at one reviewed row.
    # +2: the deployment-wide TingTing integration adds app/services/tingting_api.py.
    # That module imports get_http_client, so the whole file is provider transport:
    # one reviewed egress row (TingtingApiService._send's single `client.request`)
    # plus its two `db.get` configuration reads — but the per-project integration
    # (-1 row: its egress site) was retired with the section it configured.
    # +2: multi-OA adds the per-account credential read (resolve_zalo) and the
    # account-scoped credential delete (clear_oa_account_credentials).
    # +2: the reset flow's channel scope reads the stored OA pin
    # (TingtingApiService.reset_oa_id's db.get) and the runner resolves the
    # conversation's channel account through the same provider-transport file.
    # +3: the reset flow keeps its state server-side (TingtingFlowStore), so
    # app/services/tingting_api.py gains a Redis `get` in load() plus the
    # `delete` in clear(), and the dispatcher names the send_tingting_otp tool
    # call — the flow tools themselves open no new egress site.
    "provider_boundary": 92,
    # -32: the integrations router became transport-only. Its 30+ rows were
    # mostly route-decorator artifacts of the forced by-path scan (every
    # `@router.get` counted as a provider `get`); the real transport sites
    # moved with their logic — the OA diagnostic OAuth POST and the bot probe
    # reads into services/integrations/zalo_diagnostics.py (forced by path,
    # same treatment the router had), while the LLM probe request-merging
    # reads landed in llm_diagnostics.py, which is not a provider-transport
    # file. The Graph calls of the Facebook flow were already inventoried at
    # their channels/providers home and are unchanged.
    # -8: the integration_settings decomposition split the single module into a
    # package; the OA refresh transport (post + eval + its surrounding reads)
    # moved into providers/zalo.py, which still carries the get_http_client
    # marker, while the LLM/Facebook resolve `._load` dict reads and the
    # storage-layer db.get upserts landed in modules that are not
    # provider-transport files. The call sites themselves are unchanged, only
    # their home module moved.
    # -3: the clients.py decomposition moved the routed-prefetch wrapper and the
    # job-authority readers (dict `.get` rows) into prefetch.py / grounding.py,
    # which are not provider-transport files; the call sites themselves are
    # unchanged, only their home module moved.
    # +3 for the Messenger profile-enrichment chain, which fetches the sender's
    # gender so replies can address them as anh / chị:
    # webhooks.facebook_webhook -> composition.enqueue_messenger_profile_enrichment
    # -> persistence_worker.enqueue_enrich_messenger_profile -> enqueue_job.
    # +1: a turn that held the per-chat mutex hands the conversation to a newer
    # inbound the ingress guard dropped, via chatbot_worker._handoff_to_newer_inbound
    # -> enqueue_latest_unanswered_worker_message.
    "queue_producer": 42,
    # -1: the custom provider stopped reading a stored context-window row (the
    # field left the settings UI), so resolve_custom_llm._load's `get` count
    # drops 7→6 at the same site.
    # -1: the direct-context capacity resolver no longer calls the OpenRouter
    # model-metadata endpoint (every chatbot agent now runs the fixed 1M window),
    # removing knowledge_base_capacity's provider-transport `get` site.
    # +1: recovered turns go to their own low-priority queue, so the sweep's
    # enqueue site is enqueue_recovery_chat_run instead of enqueue_chat_run.
}
# Digest refresh only: webhook.ZaloWebhookService.handle replaced its two
# post-write `svc.get(conv.id)` re-reads with the column-scoped
# `db.refresh(conv, _GUARD_REFRESH_COLUMNS)`, so the `get` invocation count at
# that one reviewed site drops 3→1. No site was added, removed, or moved, so
# EXPECTED_BROAD_BOUNDARY_COUNTS (distinct call sites) is unchanged.
EXPECTED_BROAD_BOUNDARY_SHA256 = "644e4ce9284115a594d3d77efcd040f8062246bea5219dcbb2b5f1bdfb5de2b1"
CALL_CATEGORIES = {
    "queue_producer": {
        "enqueue",
        "enqueue_job",
        "enqueue_chat_run",
        "enqueue_recovery_chat_run",
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
                # `eval` is the Redis Lua CAS the ownership-checked lock releases
                # use (REL-03); it mutates state, so it belongs in the snapshot
                # the same way `delete` did.
                and name
                in {"get", "getdel", "post", "put", "patch", "delete", "request", "eval"}
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
        relative_path = path.relative_to(APP_DIR.parent).as_posix()
        source = path.read_text(encoding="utf-8")
        # The Zalo diagnostics module issues the raw OA OAuth POST through the
        # integration HTTP client without importing httpx itself, so it is
        # forced into the reviewed surface by path — the same treatment the
        # integrations router received before the probes moved out of it.
        provider_transport = any(
            marker in source for marker in ("get_http_client", "import httpx", "from httpx")
        ) or relative_path.endswith("services/integrations/zalo_diagnostics.py")
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
