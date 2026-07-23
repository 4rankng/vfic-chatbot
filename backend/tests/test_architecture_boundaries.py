"""Freeze exact dependency inversions while the DDD migration removes them.

The baseline is deliberately one-way: removing a legacy edge passes, while a
new importer-to-symbol edge fails. Relative imports and the TypeScript import
forms supported by the application are normalized before comparison.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]

# Generated from the accepted 2026-07-22 baseline. Entries are exact normalized
# rule|importer|target edges; this is intentionally data, not a runtime snapshot.
ALLOWED_EDGES: frozenset[str] = frozenset(
    line.strip()
    for line in """
api_outward|backend/app/api/conversations.py|app.core.config:get_settings
api_outward|backend/app/api/conversations.py|app.core.db:get_db
api_outward|backend/app/api/conversations.py|app.graph.factories:build_deps
api_outward|backend/app/api/conversations.py|app.graph.runner:run_turn
api_outward|backend/app/api/conversations.py|app.graph.types:BotRunState
api_outward|backend/app/api/conversations.py|app.models.conversation:Conversation
api_outward|backend/app/api/conversations.py|app.models.conversation:ConversationMode
api_outward|backend/app/api/conversations.py|app.models.conversation:ConversationStatus
api_outward|backend/app/api/conversations.py|app.models.user:Role
api_outward|backend/app/api/conversations.py|app.models.user:User
api_outward|backend/app/api/conversations.py|app.workers.chatbot_worker:enqueue_chat_run
api_outward|backend/app/api/integrations.py|app.core.config:ZALO_BOT_WEBHOOK_URL
api_outward|backend/app/api/integrations.py|app.core.config:get_settings
api_outward|backend/app/api/integrations.py|app.core.db:get_db
api_outward|backend/app/api/integrations.py|app.core.http:get_http_client
api_outward|backend/app/api/integrations.py|app.core.redis:get_redis
api_outward|backend/app/api/integrations.py|app.models.user:Role
api_outward|backend/app/api/integrations.py|app.models.user:User
api_outward|backend/app/api/leads.py|app.core.db:get_db
api_outward|backend/app/api/leads.py|app.models.lead:LeadStage
api_outward|backend/app/api/leads.py|app.models.user:User
api_outward|backend/app/api/personas.py|app.core.db:get_db
api_outward|backend/app/api/personas.py|app.models.user:User
api_outward|backend/app/api/webhooks.py|app.core.config:get_settings
api_outward|backend/app/api/webhooks.py|app.core.db:get_db
api_outward|backend/app/api/webhooks.py|app.models.contact:ContactChannelIdentity
api_outward|backend/app/api/webhooks.py|app.models.conversation:Conversation
api_outward|backend/app/api/webhooks.py|app.models.conversation:DeliveryStatus
api_outward|backend/app/api/webhooks.py|app.models.conversation:Message
api_outward|backend/app/api/webhooks.py|app.workers.chatbot_worker:enqueue_chat_run
""".splitlines()
    if line.strip()
)

_TS_SCANNER = Path(__file__).parent / "helpers" / "typescript_import_scanner.cjs"


def _resolve_python_module(path: Path, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = list(path.relative_to(REPO_ROOT / "backend").with_suffix("").parts[:-1])
    keep = max(0, len(package) - (node.level - 1))
    parts = package[:keep]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _python_import_targets(path: Path, source: str) -> set[str]:
    targets: set[str] = set()
    tree = ast.parse(source)
    importlib_aliases = {"importlib"}
    import_module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            importlib_aliases.update(
                alias.asname or alias.name for alias in node.names if alias.name == "importlib"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            import_module_aliases.update(
                alias.asname or alias.name for alias in node.names if alias.name == "import_module"
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = _resolve_python_module(path, node)
            if node.module:
                for alias in node.names:
                    targets.add(f"{module}:{alias.name}")
                    if module == "app" and alias.name in {
                        "api",
                        "core",
                        "graph",
                        "models",
                        "workers",
                    }:
                        targets.add(f"app.{alias.name}")
            else:
                targets.update(f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Call):
            first_arg = node.args[0] if node.args else None
            name_keyword = next((kw.value for kw in node.keywords if kw.arg == "name"), None)
            import_arg = first_arg or name_keyword
            if not isinstance(import_arg, ast.Constant):
                continue
            imported = import_arg.value
            if not isinstance(imported, str):
                continue
            package_node = (
                node.args[1]
                if len(node.args) > 1
                else next((kw.value for kw in node.keywords if kw.arg == "package"), None)
            )
            if imported.startswith(".") and isinstance(package_node, ast.Constant):
                package = package_node.value
                if isinstance(package, str) and package:
                    try:
                        imported = importlib.util.resolve_name(imported, package)
                    except ImportError:
                        pass
            if isinstance(node.func, ast.Name) and node.func.id == "__import__":
                targets.add(imported)
            elif isinstance(node.func, ast.Name) and node.func.id in import_module_aliases:
                targets.add(imported)
            elif (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in importlib_aliases
                and node.func.attr == "import_module"
            ):
                targets.add(imported)
    return targets


def _normalize_posix(module: str) -> str:
    parts: list[str] = []
    for part in PurePosixPath(module).parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    return "/".join(parts)


def _resolve_typescript_module(path: Path, module: str) -> str:
    if "\\" in module:
        try:
            module = re.sub(
                r"\\u\{([0-9a-fA-F]+)\}",
                lambda match: chr(int(match.group(1), 16)),
                module,
            )
            cooked = ast.literal_eval(f'"{module}"')
            if isinstance(cooked, str):
                module = cooked
        except (SyntaxError, ValueError):
            pass
    if module.startswith("@/"):
        return _normalize_posix(f"frontend/src/{module[2:]}")
    if module.startswith("."):
        base = PurePosixPath(path.relative_to(REPO_ROOT).parent.as_posix())
        return _normalize_posix((base / module).as_posix())
    return module


def _typescript_import_targets_many(files: list[tuple[Path, str]]) -> dict[Path, set[str]]:
    payload = [{"path": path.as_posix(), "source": source} for path, source in files]
    completed = subprocess.run(
        ["node", str(_TS_SCANNER)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        cwd=REPO_ROOT,
    )
    parsed: dict[str, list[str]] = json.loads(completed.stdout)
    return {
        path: {_resolve_typescript_module(path, module) for module in parsed[path.as_posix()]}
        for path, _source in files
    }


def _typescript_import_targets(path: Path, source: str) -> set[str]:
    return _typescript_import_targets_many([(path, source)])[path]


def _backend_rule(rel: str, target: str) -> str | None:
    module = target.split(":", 1)[0]
    pure_backend_prefixes = (
        "backend/app/shared/domain/",
        "backend/app/shared/application/",
        "backend/app/identity/domain/",
        "backend/app/identity/application/",
        "backend/app/access/domain/",
        "backend/app/access/application/",
        "backend/app/installation/domain/",
        "backend/app/installation/application/",
        "backend/app/project_knowledge/domain/",
        "backend/app/project_knowledge/application/",
        "backend/app/conversation_messaging/domain/",
        "backend/app/conversation_messaging/application/",
        "backend/app/recruitment/domain/",
        "backend/app/recruitment/application/",
        "backend/app/reporting/application/",
    )
    pure_backend_file = rel.startswith("backend/app/integrations/") and rel.endswith(
        ("/domain.py", "/application.py")
    )
    if (rel.startswith(pure_backend_prefixes) or pure_backend_file) and module.startswith(
        (
            "fastapi",
            "httpx",
            "pydantic",
            "redis",
            "rq",
            "socketio",
            "sqlalchemy",
            "app.api",
            "app.channels",
            "app.core",
            "app.graph",
            "app.models",
            "app.services",
            "app.workers",
        )
    ):
        return "pure_outward"
    if rel.startswith("backend/app/services/") and module.startswith(
        ("app.graph", "app.workers", "app.api")
    ):
        return "service_outward"
    if rel.startswith("backend/app/api/") and module.startswith(
        ("app.models", "app.core", "app.graph", "app.workers")
    ):
        return "api_outward"
    if rel.startswith("backend/app/schemas/") and module.startswith(("app.models", "app.core")):
        return "schema_infra"
    return None


_CONVERSATION_ROOT = "frontend/src/components/atomic-crm/conversations"
_CONVERSATION_RESET_FACADE = f"{_CONVERSATION_ROOT}/reset-runtime"
_CONVERSATION_VALUE_TYPE_TARGETS = (
    "frontend/src/components/atomic-crm/types",
    f"{_CONVERSATION_ROOT}/domain",
)
_CONVERSATION_LEGACY_STATE_TARGETS = (
    f"{_CONVERSATION_ROOT}/chatRepository",
    f"{_CONVERSATION_ROOT}/messageStore",
)

_FRONTEND_LAYERED_FEATURE_ROOTS = tuple(
    f"frontend/src/components/atomic-crm/{feature}"
    for feature in ("knowledge", "leads", "personas", "projects", "reporting")
)
def _has_module_prefix(target: str, prefix: str) -> bool:
    return target == prefix or target.startswith(f"{prefix}/")


def _is_conversation_layer_test(rel: str) -> bool:
    return rel.startswith(f"{_CONVERSATION_ROOT}/") and ".test." in Path(rel).name


def _is_conversation_layer_module(rel: str) -> bool:
    return any(
        _has_module_prefix(rel, f"{_CONVERSATION_ROOT}/{layer}")
        for layer in ("domain", "application", "infrastructure", "presentation")
    )


def _conversation_layer_rule(rel: str, target: str) -> str | None:
    """Keep the conversation DDD layers one-way without a grandfathered edge."""
    if _is_conversation_layer_test(rel):
        return None

    root_reset = "frontend/src/components/atomic-crm/root/reset-runtime-state.ts"
    if rel == root_reset and _has_module_prefix(target, _CONVERSATION_ROOT):
        return None if target == _CONVERSATION_RESET_FACADE else "conversation_root_reset"

    domain = f"{_CONVERSATION_ROOT}/domain"
    application = f"{_CONVERSATION_ROOT}/application"
    infrastructure = f"{_CONVERSATION_ROOT}/infrastructure"
    presentation = f"{_CONVERSATION_ROOT}/presentation"
    framework_or_browser_target = target.startswith(
        ("react", "ra-core", "zustand", "@tanstack/")
    )
    outer_infrastructure_target = target.startswith(
        (
            "frontend/src/lib/apiClient",
            "frontend/src/lib/runtime-config",
            "frontend/src/lib/vfic",
        )
    ) or any(
        _has_module_prefix(target, prefix)
        for prefix in (
            "frontend/src/components/atomic-crm/providers",
            "frontend/src/components/atomic-crm/root",
        )
    )

    if _has_module_prefix(rel, domain):
        if (
            framework_or_browser_target
            or outer_infrastructure_target
            or not any(
                _has_module_prefix(target, allowed)
                for allowed in _CONVERSATION_VALUE_TYPE_TARGETS
            )
        ):
            return "conversation_domain_outward"

    if _has_module_prefix(rel, application):
        if (
            framework_or_browser_target
            or outer_infrastructure_target
            or _has_module_prefix(target, infrastructure)
            or _has_module_prefix(target, presentation)
            or not any(
                _has_module_prefix(target, allowed)
                for allowed in (*_CONVERSATION_VALUE_TYPE_TARGETS, application)
            )
        ):
            return "conversation_application_outward"

    if _has_module_prefix(rel, infrastructure) and (
        _has_module_prefix(target, presentation)
        or _has_module_prefix(target, "frontend/src/components/atomic-crm/capabilities")
    ):
        return "conversation_infrastructure_outward"

    if _has_module_prefix(rel, presentation) and (
        _has_module_prefix(target, infrastructure)
        or outer_infrastructure_target
        or any(
            _has_module_prefix(target, legacy)
            for legacy in _CONVERSATION_LEGACY_STATE_TARGETS
        )
    ):
        return "conversation_presentation_outward"

    return None


def _feature_root(rel: str) -> str | None:
    return next(
        (
            root
            for root in _FRONTEND_LAYERED_FEATURE_ROOTS
            if _has_module_prefix(rel, root)
        ),
        None,
    )


def _is_feature_layer_module(rel: str) -> bool:
    root = _feature_root(rel)
    return root is not None and any(
        _has_module_prefix(rel, f"{root}/{layer}")
        for layer in ("domain", "application", "infrastructure")
    )


def _is_feature_composition_module(rel: str) -> bool:
    """Recognize feature-local composition roots by the service naming convention."""
    root = _feature_root(rel)
    if root is None or PurePosixPath(rel).parent.as_posix() != root:
        return False
    return PurePosixPath(rel).stem.lower().endswith("service")


def _feature_layer_rule(rel: str, target: str) -> str | None:
    """Keep migrated frontend feature layers inward-only without exceptions."""
    root = _feature_root(rel)
    if root is None or ".test." in Path(rel).name:
        return None

    domain = f"{root}/domain"
    application = f"{root}/application"
    infrastructure = f"{root}/infrastructure"
    shared_types = "frontend/src/components/atomic-crm/types"
    framework_target = target.startswith(
        (
            "react",
            "ra-core",
            "zustand",
            "@tanstack/",
            "frontend/src/lib",
            "frontend/src/components/atomic-crm/providers",
        )
    )

    if _has_module_prefix(rel, domain):
        if (
            framework_target
            or not (
                _has_module_prefix(target, domain)
                or _has_module_prefix(target, shared_types)
            )
        ):
            return "frontend_feature_domain_outward"

    if _has_module_prefix(rel, application):
        if (
            framework_target
            or _has_module_prefix(target, infrastructure)
            or not (
                _has_module_prefix(target, domain)
                or _has_module_prefix(target, application)
                or _has_module_prefix(target, shared_types)
            )
        ):
            return "frontend_feature_application_outward"

    if _has_module_prefix(rel, infrastructure):
        if _has_module_prefix(target, root) and not any(
            _has_module_prefix(target, allowed)
            for allowed in (domain, application, infrastructure)
        ):
            return "frontend_feature_infrastructure_outward"

    if (
        not _is_feature_composition_module(rel)
        and not any(
            _has_module_prefix(rel, layer)
            for layer in (domain, application, infrastructure)
        )
        and _has_module_prefix(target, infrastructure)
    ):
        return "frontend_feature_presentation_outward"

    return None


def _frontend_rule(rel: str, target: str) -> str | None:
    if rule := _conversation_layer_rule(rel, target):
        return rule
    if _is_conversation_layer_module(rel):
        return None
    if rule := _feature_layer_rule(rel, target):
        return rule
    if _is_feature_layer_module(rel):
        return None
    if rel.startswith("frontend/src/lib/vfic/") and target.startswith(
        "frontend/src/components/atomic-crm"
    ):
        return "lib_product"
    if rel.startswith("frontend/src/components/atomic-crm/") and target.startswith(
        "frontend/src/lib/vfic"
    ):
        return "product_lib"
    return None


def _current_edges() -> set[str]:
    found: set[str] = set()
    for path in (REPO_ROOT / "backend/app").rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        for target in _python_import_targets(path, path.read_text()):
            if rule := _backend_rule(rel, target):
                found.add(f"{rule}|{rel}|{target}")

    frontend_files = [
        (path, path.read_text(errors="ignore"))
        for path in (REPO_ROOT / "frontend/src").rglob("*")
        if path.is_file() and path.suffix in {".ts", ".tsx"}
    ]
    for path, targets in _typescript_import_targets_many(frontend_files).items():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for target in targets:
            if rule := _frontend_rule(rel, target):
                found.add(f"{rule}|{rel}|{target}")
    return found


def test_no_new_layer_boundary_violations() -> None:
    excess = sorted(_current_edges() - ALLOWED_EDGES)
    assert not excess, "New architecture boundary edges:\n" + "\n".join(excess)


def test_boundary_allowlist_only_names_existing_files() -> None:
    missing = sorted(
        edge for edge in ALLOWED_EDGES if not (REPO_ROOT / edge.split("|", 2)[1]).is_file()
    )
    assert not missing, f"Remove stale architecture allowlist entries: {missing}"


def test_boundary_allowlist_only_contains_active_edges() -> None:
    stale = sorted(ALLOWED_EDGES - _current_edges())
    assert not stale, "Remove inactive architecture allowlist edges:\n" + "\n".join(stale)


def test_python_scanner_normalizes_relative_imports_and_symbols() -> None:
    path = REPO_ROOT / "backend/app/api/example.py"
    targets = _python_import_targets(
        path,
        "from ..models import User, Role\n"
        "from .. import models\n"
        "from app.models import Lead\n"
        "from app import core, graph, models, workers\n"
        "from app import api\n"
        "import importlib as il\n"
        "from importlib import import_module as load_module\n"
        "dynamic = il.import_module('app.models.job')\n"
        "aliased = load_module('app.models.company')\n"
        "keyword = il.import_module(name='app.models.user')\n"
        "relative = il.import_module('.models', package='app')\n"
        "positional_relative = il.import_module('.models', 'app')\n"
        "legacy = __import__('app.models.persona')\n",
    )
    assert {
        "app.models:User",
        "app.models:Role",
        "app.models",
        "app.models:Lead",
        "app.core",
        "app.api",
        "app.graph",
        "app.models",
        "app.workers",
        "app.models.job",
        "app.models.company",
        "app.models.persona",
    } <= targets
    for target in {"app.core", "app.graph", "app.models", "app.workers"}:
        assert _backend_rule("backend/app/api/example.py", target) == "api_outward"
    assert _backend_rule("backend/app/services/example.py", "app.api") == "service_outward"


def test_shared_kernel_rejects_framework_and_infrastructure_imports() -> None:
    importer = "backend/app/shared/application/example.py"
    for target in (
        "fastapi:Depends",
        "httpx:AsyncClient",
        "sqlalchemy:select",
        "app.models.user:User",
        "app.channels.http_error_classification:classify_transport_error",
        "app.workers.utils:enqueue_job",
    ):
        assert _backend_rule(importer, target) == "pure_outward"


def test_context_domain_and_application_modules_reject_outward_imports() -> None:
    for importer in (
        "backend/app/identity/application/example.py",
        "backend/app/access/domain/example.py",
        "backend/app/installation/domain/example.py",
        "backend/app/integrations/facebook_oauth/domain.py",
        "backend/app/integrations/facebook_oauth/application.py",
        "backend/app/project_knowledge/domain/example.py",
        "backend/app/project_knowledge/application/example.py",
        "backend/app/conversation_messaging/domain/example.py",
        "backend/app/conversation_messaging/application/example.py",
        "backend/app/recruitment/domain/example.py",
        "backend/app/recruitment/application/example.py",
        "backend/app/reporting/application/example.py",
    ):
        for target in (
            "fastapi:Depends",
            "pydantic:BaseModel",
            "sqlalchemy:select",
            "redis.asyncio:Redis",
            "rq:Queue",
            "socketio:AsyncServer",
            "app.api.auth_dependencies:get_current_user",
            "app.core.security:decode_token",
            "app.models.user:User",
            "app.services.installation.service:InstallationService",
            "app.workers.chatbot_worker:enqueue_chat_run",
        ):
            assert _backend_rule(importer, target) == "pure_outward"


def test_project_knowledge_package_has_no_graph_or_worker_backedge() -> None:
    context_root = REPO_ROOT / "backend/app/project_knowledge"
    forbidden: list[str] = []
    for path in context_root.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        targets = _python_import_targets(path, path.read_text())
        for target in targets:
            module = target.split(":", 1)[0]
            if module.startswith(("app.graph", "app.workers")):
                forbidden.append(f"{rel}|{target}")
    assert not forbidden, "Project/knowledge context backedges:\n" + "\n".join(
        sorted(forbidden)
    )


def test_conversation_messaging_package_has_no_graph_or_worker_backedge() -> None:
    context_root = REPO_ROOT / "backend/app/conversation_messaging"
    forbidden: list[str] = []
    for path in context_root.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        targets = _python_import_targets(path, path.read_text())
        for target in targets:
            module = target.split(":", 1)[0]
            if module.startswith(("app.graph", "app.workers")):
                forbidden.append(f"{rel}|{target}")
    assert not forbidden, "Conversation/messaging context backedges:\n" + "\n".join(
        sorted(forbidden)
    )


def test_recruitment_package_has_no_graph_or_worker_backedge() -> None:
    context_root = REPO_ROOT / "backend/app/recruitment"
    forbidden: list[str] = []
    for path in context_root.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        targets = _python_import_targets(path, path.read_text())
        for target in targets:
            module = target.split(":", 1)[0]
            if module.startswith(("app.graph", "app.workers")):
                forbidden.append(f"{rel}|{target}")
    assert not forbidden, "Recruitment context backedges:\n" + "\n".join(
        sorted(forbidden)
    )


def test_typescript_scanner_covers_supported_import_forms_and_aliases() -> None:
    path = REPO_ROOT / "frontend/src/components/atomic-crm/example.ts"
    targets = _typescript_import_targets(
        path,
        """
        import '@/lib/vfic/side-effect';
        const lazy = import('@/lib/vfic/lazy');
        const legacy = require('@/lib/vfic/legacy');
        const template = import(`@/lib/vfic/template`);
        const codepointTemplate = import(`\\u{40}/lib/vfic/codepoint-template`);
        const chunked = import(/* chunk */ '@/lib/vfic/chunked');
        const commented = require(/* legacy */ '@/lib/vfic/commented');
        const lineComment = import(
          // chunk
          '@/lib/vfic/line-comment'
        );
        const outerImport = import /* chunk */ ('@/lib/vfic/outer-import');
        const outerRequire = require /* compatibility */ ('@/lib/vfic/outer-require');
        import '@/lib/../lib/vfic/normalized';
        import '\\x40/lib/vfic/escaped';
        import '\\u{40}/lib/vfic/codepoint-escaped';
        import thing from '../../lib/vfic/relative';
        """,
    )
    assert targets == {
        "frontend/src/lib/vfic/side-effect",
        "frontend/src/lib/vfic/lazy",
        "frontend/src/lib/vfic/legacy",
        "frontend/src/lib/vfic/template",
        "frontend/src/lib/vfic/codepoint-template",
        "frontend/src/lib/vfic/chunked",
        "frontend/src/lib/vfic/commented",
        "frontend/src/lib/vfic/line-comment",
        "frontend/src/lib/vfic/outer-import",
        "frontend/src/lib/vfic/outer-require",
        "frontend/src/lib/vfic/normalized",
        "frontend/src/lib/vfic/escaped",
        "frontend/src/lib/vfic/codepoint-escaped",
        "frontend/src/lib/vfic/relative",
    }
    assert all(
        _frontend_rule("frontend/src/components/atomic-crm/example.ts", target) == "product_lib"
        for target in targets
    )


def test_typescript_scanner_ignores_commented_out_imports() -> None:
    path = REPO_ROOT / "frontend/src/components/atomic-crm/example.ts"
    targets = _typescript_import_targets(
        path,
        """
        // import '@/lib/vfic/comment-only';
        /* from '@/lib/vfic/block-only' */
        const text = "import '@/lib/vfic/string-only'";
        const callText = " import('@/lib/vfic/call-string-only')";
        const templateText = ` import('@/lib/vfic/template-string-only')`;
        const expression = `value: ${import('@/lib/vfic/template-expression')}`;
        """,
    )
    assert targets == {"frontend/src/lib/vfic/template-expression"}


def test_typescript_scanner_does_not_lose_imports_after_regex_literals() -> None:
    path = REPO_ROOT / "frontend/src/components/atomic-crm/example.ts"
    targets = _typescript_import_targets(
        path,
        "const quote = /[\"']/;\n"
        "const slash = /[//]/;\n"
        "const arrow = () => /[\"']/;\n"
        "if (value) /[\"']/.test(value);\n"
        "function* matches() { yield /[\"']/; }\n"
        "import '@/lib/vfic/static-after-regex';\n"
        "const lazy = import('@/lib/vfic/dynamic-after-regex');\n",
    )
    assert targets == {
        "frontend/src/lib/vfic/static-after-regex",
        "frontend/src/lib/vfic/dynamic-after-regex",
    }


def test_conversation_layers_have_zero_allowlist_dependency_rules() -> None:
    domain = f"{_CONVERSATION_ROOT}/domain/example.ts"
    application = f"{_CONVERSATION_ROOT}/application/example.ts"
    infrastructure = f"{_CONVERSATION_ROOT}/infrastructure/example.ts"
    presentation = f"{_CONVERSATION_ROOT}/presentation/example.tsx"

    for importer in (domain, application):
        for target in (
            "react",
            "ra-core",
            "zustand",
            "@tanstack/react-query",
            "frontend/src/lib/apiClient",
            "frontend/src/components/atomic-crm/providers/realtime/realtime-socket",
            "frontend/src/components/atomic-crm/root/reset-runtime-state",
        ):
            assert _frontend_rule(importer, target) is not None

    assert _frontend_rule(domain, f"{_CONVERSATION_ROOT}/domain/value") is None
    assert _frontend_rule(domain, "frontend/src/components/atomic-crm/types") is None
    assert _frontend_rule(application, f"{_CONVERSATION_ROOT}/domain/value") is None
    assert _frontend_rule(application, f"{_CONVERSATION_ROOT}/application/ports") is None
    assert _frontend_rule(application, f"{_CONVERSATION_ROOT}/infrastructure/repository") == (
        "conversation_application_outward"
    )
    assert (
        _frontend_rule(infrastructure, f"{_CONVERSATION_ROOT}/presentation/view")
        == "conversation_infrastructure_outward"
    )
    assert _frontend_rule(
        infrastructure,
        "frontend/src/components/atomic-crm/capabilities/static-recruitment-runtime",
    ) == "conversation_infrastructure_outward"
    assert (
        _frontend_rule(
            infrastructure,
            "frontend/src/components/atomic-crm/providers/realtime/realtime-socket",
        )
        is None
    )

    for target in (
        f"{_CONVERSATION_ROOT}/infrastructure/repository",
        "frontend/src/lib/apiClient",
        "frontend/src/components/atomic-crm/providers/realtime/realtime-socket",
        "frontend/src/components/atomic-crm/root/reset-runtime-state",
        f"{_CONVERSATION_ROOT}/chatRepository",
        f"{_CONVERSATION_ROOT}/messageStore",
    ):
        assert _frontend_rule(presentation, target) == "conversation_presentation_outward"


def test_root_reset_can_only_import_the_public_conversation_reset_facade() -> None:
    importer = "frontend/src/components/atomic-crm/root/reset-runtime-state.ts"
    assert _frontend_rule(importer, _CONVERSATION_RESET_FACADE) is None
    assert _frontend_rule(importer, f"{_CONVERSATION_ROOT}/messageStore") == (
        "conversation_root_reset"
    )
    assert (
        _frontend_rule(
            importer,
            f"{_CONVERSATION_ROOT}/infrastructure/runtime-epoch-adapter",
        )
        == "conversation_root_reset"
    )


def test_migrated_frontend_feature_layers_have_zero_allowlist_rules() -> None:
    for root in _FRONTEND_LAYERED_FEATURE_ROOTS:
        domain = f"{root}/domain/example.ts"
        application = f"{root}/application/example.ts"
        infrastructure = f"{root}/infrastructure/example.ts"
        presentation = f"{root}/Example.tsx"

        for importer in (domain, application):
            for target in (
                "react",
                "ra-core",
                "@tanstack/react-query",
                "frontend/src/lib/apiClient",
                f"{root}/infrastructure/http",
            ):
                assert _frontend_rule(importer, target) is not None

        assert _frontend_rule(domain, f"{root}/domain/value") is None
        assert _frontend_rule(
            domain, "frontend/src/components/atomic-crm/types"
        ) is None
        assert _frontend_rule(application, f"{root}/domain/value") is None
        assert _frontend_rule(application, f"{root}/application/ports") is None
        assert _frontend_rule(application, f"{root}/infrastructure/http") == (
            "frontend_feature_application_outward"
        )
        assert _frontend_rule(infrastructure, f"{root}/Example") == (
            "frontend_feature_infrastructure_outward"
        )
        assert _frontend_rule(presentation, f"{root}/infrastructure/http") == (
            "frontend_feature_presentation_outward"
        )

    for root in _FRONTEND_LAYERED_FEATURE_ROOTS:
        facade = f"{root}/feature-service.ts"
        assert _is_feature_composition_module(facade)
        assert _frontend_rule(facade, f"{root}/infrastructure/http") is None
        assert not _is_feature_composition_module(f"{root}/FeaturePanel.tsx")


def test_frontend_domain_and_application_layers_do_not_use_browser_io_globals() -> None:
    # Deterministic platform value parsers such as URL and URLSearchParams are
    # allowed. This gate rejects browser state and I/O capabilities that make a
    # domain/application module depend on a concrete runtime adapter.
    browser_patterns = (
        re.compile(r"\b(?:File|FormData|Blob|AbortSignal|AbortController)\b"),
        re.compile(
            r"\b(?:window|document|navigator|history|"
            r"localStorage|sessionStorage|indexedDB)\s*\."
        ),
        re.compile(
            r"\bglobalThis\s*\.\s*(?:location|history|navigator|"
            r"localStorage|sessionStorage|indexedDB)\b"
        ),
        re.compile(
            r"\b(?:WebSocket|EventSource|BroadcastChannel|Worker)\s*\("
        ),
        re.compile(r"\bfetch\s*\("),
    )
    paths: list[Path] = []
    for root in _FRONTEND_LAYERED_FEATURE_ROOTS:
        absolute = REPO_ROOT / root
        for layer in ("domain", "application"):
            paths.extend((absolute / layer).rglob("*.ts"))
            paths.extend((absolute / layer).rglob("*.tsx"))
    paths.extend(
        REPO_ROOT
        / "frontend/src/components/atomic-crm/installation"
        / filename
        for filename in (
            "runtime-manifest-policy.ts",
            "runtime-manifest-application.ts",
        )
    )

    violations: list[str] = []
    for path in paths:
        if ".test." in path.name:
            continue
        source = path.read_text()
        for pattern in browser_patterns:
            if match := pattern.search(source):
                violations.append(
                    f"{path.relative_to(REPO_ROOT).as_posix()}|{match.group(0)}"
                )
    assert not violations, "Browser globals in pure frontend layers:\n" + "\n".join(
        sorted(violations)
    )
