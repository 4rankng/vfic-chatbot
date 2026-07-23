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
api_outward|backend/app/api/auth.py|app.core.config:get_settings
api_outward|backend/app/api/auth.py|app.core.db:get_db
api_outward|backend/app/api/auth.py|app.core.ratelimit:enforce_rate_limit
api_outward|backend/app/api/auth.py|app.core.ratelimit:enforce_rate_limit_key
api_outward|backend/app/api/auth.py|app.core.security:create_access_token
api_outward|backend/app/api/auth.py|app.core.security:create_refresh_token
api_outward|backend/app/api/auth.py|app.core.security:decode_token
api_outward|backend/app/api/auth.py|app.core.security:hash_password
api_outward|backend/app/api/auth.py|app.core.security:verify_password
api_outward|backend/app/api/auth.py|app.models.user:User
api_outward|backend/app/api/bot_runs.py|app.core.db:get_db
api_outward|backend/app/api/bot_runs.py|app.models.conversation:BotRunOutcome
api_outward|backend/app/api/bot_runs.py|app.models.user:User
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
api_outward|backend/app/api/dashboard.py|app.core.db:get_db
api_outward|backend/app/api/dashboard.py|app.models.user:User
api_outward|backend/app/api/dependencies.py|app.core.db:get_db
api_outward|backend/app/api/dependencies.py|app.graph.clients:build_embedder
api_outward|backend/app/api/installation.py|app.core.db:get_db
api_outward|backend/app/api/installation.py|app.models.user:User
api_outward|backend/app/api/integrations.py|app.core.config:ZALO_BOT_WEBHOOK_URL
api_outward|backend/app/api/integrations.py|app.core.config:get_settings
api_outward|backend/app/api/integrations.py|app.core.db:get_db
api_outward|backend/app/api/integrations.py|app.core.http:get_http_client
api_outward|backend/app/api/integrations.py|app.core.redis:get_redis
api_outward|backend/app/api/integrations.py|app.models.user:Role
api_outward|backend/app/api/integrations.py|app.models.user:User
api_outward|backend/app/api/jobs.py|app.core.db:get_db
api_outward|backend/app/api/jobs.py|app.models.job:JobStatus
api_outward|backend/app/api/jobs.py|app.models.user:User
api_outward|backend/app/api/knowledge.py|app.core.cache:bump_cache_version
api_outward|backend/app/api/knowledge.py|app.core.db:get_db
api_outward|backend/app/api/knowledge.py|app.core.redis:get_redis
api_outward|backend/app/api/knowledge.py|app.models.company:Project
api_outward|backend/app/api/knowledge.py|app.models.external_source_sync_state:ExternalSourceSyncState
api_outward|backend/app/api/knowledge.py|app.models.knowledge:KBTextFile
api_outward|backend/app/api/knowledge.py|app.models.knowledge:KBVersion
api_outward|backend/app/api/knowledge.py|app.models.knowledge:KBVersionStatus
api_outward|backend/app/api/knowledge.py|app.models.knowledge:KnowledgeDocument
api_outward|backend/app/api/knowledge.py|app.models.knowledge:KnowledgeStatus
api_outward|backend/app/api/knowledge.py|app.models.user:User
api_outward|backend/app/api/knowledge_bases.py|app.core.db:get_db
api_outward|backend/app/api/knowledge_bases.py|app.models.company:Company
api_outward|backend/app/api/knowledge_bases.py|app.models.company:Project
api_outward|backend/app/api/knowledge_bases.py|app.models.job:Job
api_outward|backend/app/api/knowledge_bases.py|app.models.job:JobStatus
api_outward|backend/app/api/knowledge_bases.py|app.models.knowledge:KnowledgeBase
api_outward|backend/app/api/knowledge_bases.py|app.models.knowledge:KnowledgeBaseDirectFile
api_outward|backend/app/api/knowledge_bases.py|app.models.knowledge:KnowledgeDocument
api_outward|backend/app/api/knowledge_bases.py|app.models.persona:Persona
api_outward|backend/app/api/knowledge_bases.py|app.models.user:User
api_outward|backend/app/api/leads.py|app.core.db:get_db
api_outward|backend/app/api/leads.py|app.models.lead:LeadStage
api_outward|backend/app/api/leads.py|app.models.user:User
api_outward|backend/app/api/performance.py|app.core.cache:cache_get_json
api_outward|backend/app/api/performance.py|app.core.cache:cache_set_json
api_outward|backend/app/api/performance.py|app.core.db:async_session
api_outward|backend/app/api/performance.py|app.core.ops_health:collect_queue_health
api_outward|backend/app/api/performance.py|app.core.redis:get_redis
api_outward|backend/app/api/performance.py|app.models.user:User
api_outward|backend/app/api/personas.py|app.core.db:get_db
api_outward|backend/app/api/personas.py|app.models.user:User
api_outward|backend/app/api/projects.py|app.core.db:get_db
api_outward|backend/app/api/projects.py|app.models.user:User
api_outward|backend/app/api/users.py|app.core.db:get_db
api_outward|backend/app/api/users.py|app.models.user:Role
api_outward|backend/app/api/users.py|app.models.user:User
api_outward|backend/app/api/webhooks.py|app.core.config:get_settings
api_outward|backend/app/api/webhooks.py|app.core.db:get_db
api_outward|backend/app/api/webhooks.py|app.models.contact:ContactChannelIdentity
api_outward|backend/app/api/webhooks.py|app.models.conversation:Conversation
api_outward|backend/app/api/webhooks.py|app.models.conversation:DeliveryStatus
api_outward|backend/app/api/webhooks.py|app.models.conversation:Message
api_outward|backend/app/api/webhooks.py|app.workers.chatbot_worker:enqueue_chat_run
lib_product|frontend/src/lib/vfic/humanReplyService.ts|frontend/src/components/atomic-crm/providers/rest/api
lib_product|frontend/src/lib/vfic/knowledgeService.ts|frontend/src/components/atomic-crm/providers/rest/api
lib_product|frontend/src/lib/vfic/knowledgeService.ts|frontend/src/components/atomic-crm/types
lib_product|frontend/src/lib/vfic/realtimeSocket.ts|frontend/src/components/atomic-crm/providers/rest/api
product_lib|frontend/src/components/atomic-crm/capabilities/recruitment/index.tsx|frontend/src/lib/vfic/realtimeSocket
product_lib|frontend/src/components/atomic-crm/conversations/ChatThread.tsx|frontend/src/lib/vfic/humanReplyService
product_lib|frontend/src/components/atomic-crm/conversations/chatRepository.ts|frontend/src/lib/vfic/realtimeSocket
product_lib|frontend/src/components/atomic-crm/conversations/useConversationRealtime.ts|frontend/src/lib/vfic/realtimeSocket
product_lib|frontend/src/components/atomic-crm/knowledge/InlineKnowledgeUploader.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/knowledge/KnowledgeDetailPanel.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/knowledge/KnowledgeSourceList.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/knowledge/KnowledgeSourceShow.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/knowledge/KnowledgeUpload.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/knowledge/KnowledgeVersionManager.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/knowledge/StoredKnowledgePanel.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/personas/PersonaAssignments.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/personas/PersonaEdit.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/personas/PersonaForm.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/personas/PersonaList.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/projects/ExternalSourceLinkForm.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/projects/ExternalSourceList.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/projects/ProjectBusTimetable.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/projects/ProjectFaqEditor.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/projects/ProjectFeatures.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/projects/ProjectKnowledgePanel.test.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/projects/ProjectKnowledgePanel.tsx|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/projects/singlePageSheetUrl.test.ts|frontend/src/lib/vfic/knowledgeService
product_lib|frontend/src/components/atomic-crm/providers/rest/api.ts|frontend/src/lib/vfic/config
product_lib|frontend/src/components/atomic-crm/providers/rest/authProvider.ts|frontend/src/lib/vfic/realtimeSocket
product_lib|frontend/src/components/atomic-crm/providers/rest/dataProvider.ts|frontend/src/lib/vfic/humanReplyService
product_lib|frontend/src/components/atomic-crm/root/reset-runtime-state.ts|frontend/src/lib/vfic/realtimeSocket
schema_infra|backend/app/schemas/bot_run.py|app.models.conversation:BotRunOutcome
schema_infra|backend/app/schemas/conversation.py|app.models.conversation:ConversationMode
schema_infra|backend/app/schemas/conversation.py|app.models.conversation:ConversationProjectState
schema_infra|backend/app/schemas/conversation.py|app.models.conversation:ConversationStatus
schema_infra|backend/app/schemas/conversation.py|app.models.conversation:DeliveryStatus
schema_infra|backend/app/schemas/conversation.py|app.models.conversation:MessageSender
schema_infra|backend/app/schemas/ingestion_templates.py|app.models.ingestion_template:IngestionRunStatus
schema_infra|backend/app/schemas/ingestion_templates.py|app.models.ingestion_template:TemplateVersionStatus
schema_infra|backend/app/schemas/job.py|app.models.job:JobStatus
schema_infra|backend/app/schemas/knowledge.py|app.models.knowledge:KBVersionStatus
schema_infra|backend/app/schemas/knowledge.py|app.models.knowledge:KnowledgeStatus
schema_infra|backend/app/schemas/knowledge_bases.py|app.models.knowledge:KnowledgeBaseMode
schema_infra|backend/app/schemas/lead.py|app.models.lead:FollowupStatus
schema_infra|backend/app/schemas/lead.py|app.models.lead:LeadScore
schema_infra|backend/app/schemas/lead.py|app.models.lead:LeadStage
schema_infra|backend/app/schemas/personas.py|app.core.config:PROACTIVE_48H_WINDOW_SECONDS
schema_infra|backend/app/schemas/personas.py|app.core.config:PROACTIVE_FOLLOWUP_CAP
schema_infra|backend/app/schemas/personas.py|app.models.lead:LeadScore
schema_infra|backend/app/schemas/personas.py|app.models.lead:LeadStage
schema_infra|backend/app/schemas/project_knowledge.py|app.models.knowledge:KnowledgeCategoryRevisionStatus
schema_infra|backend/app/schemas/projects.py|app.models.knowledge:KnowledgeBaseMode
schema_infra|backend/app/schemas/user.py|app.models.user:Role
service_outward|backend/app/services/personas/providers.py|app.graph.provider_scope:provider_from_conversation
service_outward|backend/app/services/project/service.py|app.workers.direct_context_worker:enqueue_direct_context_index
service_outward|backend/app/services/project/single_page_external_sources.py|app.workers.direct_context_worker:enqueue_direct_context_index
service_outward|backend/app/services/webhook.py|app.workers.persistence_worker:enqueue_enrich_oa_profile
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


def _frontend_rule(rel: str, target: str) -> str | None:
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
    ):
        for target in (
            "fastapi:Depends",
            "pydantic:BaseModel",
            "sqlalchemy:select",
            "redis.asyncio:Redis",
            "rq:Queue",
            "socketio:AsyncServer",
            "app.api.dependencies:get_current_user",
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
