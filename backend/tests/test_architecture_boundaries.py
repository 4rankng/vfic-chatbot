"""Freeze known dependency inversions while the DDD migration removes them.

The baseline is deliberately one-way: deleting an inversion passes; adding a new
violating file or increasing imports in an allowlisted file fails. The owning
phase for each rule is documented in ``docs/decisions/ddd-context-boundaries.md``.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]

ALLOWED_COUNTS = {
    "api_infra|backend/app/api/auth.py": 5,
    "api_infra|backend/app/api/bot_runs.py": 3,
    "api_infra|backend/app/api/conversations.py": 4,
    "api_infra|backend/app/api/dashboard.py": 2,
    "api_infra|backend/app/api/dependencies.py": 3,
    "api_infra|backend/app/api/installation.py": 2,
    "api_infra|backend/app/api/integrations.py": 5,
    "api_infra|backend/app/api/jobs.py": 3,
    "api_infra|backend/app/api/knowledge.py": 7,
    "api_infra|backend/app/api/knowledge_bases.py": 6,
    "api_infra|backend/app/api/leads.py": 3,
    "api_infra|backend/app/api/performance.py": 5,
    "api_infra|backend/app/api/personas.py": 2,
    "api_infra|backend/app/api/projects.py": 2,
    "api_infra|backend/app/api/users.py": 2,
    "api_infra|backend/app/api/webhooks.py": 4,
    "schema_infra|backend/app/schemas/bot_run.py": 1,
    "schema_infra|backend/app/schemas/conversation.py": 1,
    "schema_infra|backend/app/schemas/ingestion_templates.py": 1,
    "schema_infra|backend/app/schemas/job.py": 1,
    "schema_infra|backend/app/schemas/knowledge.py": 1,
    "schema_infra|backend/app/schemas/knowledge_bases.py": 1,
    "schema_infra|backend/app/schemas/lead.py": 1,
    "schema_infra|backend/app/schemas/personas.py": 2,
    "schema_infra|backend/app/schemas/project_knowledge.py": 1,
    "schema_infra|backend/app/schemas/projects.py": 1,
    "schema_infra|backend/app/schemas/user.py": 1,
    "service_graph|backend/app/services/conversation/__init__.py": 1,
    "service_graph|backend/app/services/conversation/state.py": 2,
    "service_graph|backend/app/services/outbox_service.py": 1,
    "service_graph|backend/app/services/personas/providers.py": 1,
    "service_graph|backend/app/services/project/faq.py": 1,
    "service_graph|backend/app/services/project/features.py": 2,
    "service_graph|backend/app/services/zalo_bot_service.py": 2,
    "service_graph|backend/app/services/zalo_oa_service.py": 1,
    "service_worker|backend/app/services/knowledge/category_service.py": 2,
    "service_worker|backend/app/services/project/single_page_external_sources.py": 2,
    "service_worker|backend/app/services/webhook.py": 1,
    "lib_product|frontend/src/lib/vfic/humanReplyService.ts": 1,
    "lib_product|frontend/src/lib/vfic/knowledgeService.ts": 2,
    "lib_product|frontend/src/lib/vfic/realtimeSocket.ts": 1,
}

for path in (
    "capabilities/recruitment/index.tsx",
    "conversations/ChatThread.tsx",
    "conversations/chatRepository.ts",
    "conversations/useConversationRealtime.ts",
    "knowledge/InlineKnowledgeUploader.tsx",
    "knowledge/KnowledgeDetailPanel.tsx",
    "knowledge/KnowledgeSourceList.tsx",
    "knowledge/KnowledgeSourceShow.tsx",
    "knowledge/KnowledgeUpload.tsx",
    "knowledge/KnowledgeVersionManager.tsx",
    "knowledge/StoredKnowledgePanel.tsx",
    "personas/PersonaAssignments.tsx",
    "personas/PersonaEdit.tsx",
    "personas/PersonaForm.tsx",
    "personas/PersonaList.tsx",
    "projects/ExternalSourceLinkForm.tsx",
    "projects/ExternalSourceList.tsx",
    "projects/ProjectBusTimetable.tsx",
    "projects/ProjectFaqEditor.tsx",
    "projects/ProjectFeatures.tsx",
    "projects/ProjectKnowledgePanel.tsx",
    "projects/singlePageSheetUrl.test.ts",
    "providers/rest/api.ts",
    "providers/rest/authProvider.ts",
    "providers/rest/dataProvider.ts",
    "root/reset-runtime-state.ts",
):
    ALLOWED_COUNTS[f"product_lib|frontend/src/components/atomic-crm/{path}"] = 1
ALLOWED_COUNTS[
    "product_lib|frontend/src/components/atomic-crm/projects/ProjectKnowledgePanel.test.tsx"
] = 2

_TS_IMPORT = re.compile(
    r'''(?:from\s+["']([^"']+)["']|import\s+[^;]*?from\s+["']([^"']+)["'])'''
)


def _backend_violations() -> Counter[str]:
    found: Counter[str] = Counter()
    for path in (REPO_ROOT / "backend/app").rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text())
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
            elif isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
        for module in modules:
            rule = None
            if rel.startswith("backend/app/services/"):
                if module.startswith("app.graph"):
                    rule = "service_graph"
                elif module.startswith("app.workers"):
                    rule = "service_worker"
            elif rel.startswith("backend/app/api/") and module.startswith(
                ("app.models", "app.core")
            ):
                rule = "api_infra"
            elif rel.startswith("backend/app/schemas/") and module.startswith(
                ("app.models", "app.core")
            ):
                rule = "schema_infra"
            if rule:
                found[f"{rule}|{rel}"] += 1
    return found


def _frontend_violations() -> Counter[str]:
    found: Counter[str] = Counter()
    for path in (REPO_ROOT / "frontend/src").rglob("*"):
        if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        for first, second in _TS_IMPORT.findall(path.read_text(errors="ignore")):
            module = first or second
            if rel.startswith("frontend/src/lib/vfic/") and "components/atomic-crm" in module:
                found[f"lib_product|{rel}"] += 1
            elif rel.startswith("frontend/src/components/atomic-crm/") and "@/lib/vfic" in module:
                found[f"product_lib|{rel}"] += 1
    return found


def test_no_new_layer_boundary_violations() -> None:
    actual = _backend_violations() + _frontend_violations()
    excess = {
        key: {"actual": count, "allowed": ALLOWED_COUNTS.get(key, 0)}
        for key, count in actual.items()
        if count > ALLOWED_COUNTS.get(key, 0)
    }
    assert not excess, f"New architecture boundary violations: {excess}"


def test_boundary_allowlist_only_names_existing_files() -> None:
    missing = [
        key for key in ALLOWED_COUNTS if not (REPO_ROOT / key.split("|", 1)[1]).is_file()
    ]
    assert not missing, f"Remove stale architecture allowlist entries: {missing}"
