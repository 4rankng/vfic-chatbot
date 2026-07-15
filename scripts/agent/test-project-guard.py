#!/usr/bin/env python3
"""Standard-library regression tests for the Claude project guard."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = ROOT / ".claude" / "hooks" / "project-guard.py"

SPEC = importlib.util.spec_from_file_location("project_guard", GUARD_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {GUARD_PATH}")
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class ProjectGuardTests(unittest.TestCase):
    def edit(self, path: str) -> tuple[str, str] | None:
        return GUARD.evaluate(
            {
                "tool_name": "Edit",
                "cwd": str(ROOT),
                "tool_input": {"file_path": str(ROOT / path)},
            }
        )

    def bash(self, command: str, cwd: Path = ROOT) -> tuple[str, str] | None:
        return GUARD.evaluate(
            {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}
        )

    def test_allows_ordinary_source_edit(self) -> None:
        self.assertIsNone(self.edit("backend/app/services/example.py"))

    def test_allows_public_env_example(self) -> None:
        self.assertIsNone(self.edit("backend/.env.example"))

    def test_denies_secret_file(self) -> None:
        decision = self.edit("backend/.env")
        self.assertIsNotNone(decision)
        self.assertEqual(decision[0], "deny")

    def test_asks_for_migration(self) -> None:
        decision = self.edit("backend/alembic/versions/0043_example.py")
        self.assertIsNotNone(decision)
        self.assertEqual(decision[0], "ask")

    def test_asks_for_bot_behavior_file(self) -> None:
        decision = self.edit("backend/app/graph/grounding.py")
        self.assertIsNotNone(decision)
        self.assertEqual(decision[0], "ask")

    def test_asks_for_versioned_persona_prompt(self) -> None:
        decision = self.edit("backend/app/services/personas/templates/persona_v1.md")
        self.assertIsNotNone(decision)
        self.assertEqual(decision[0], "ask")

    def test_denies_destructive_git_command(self) -> None:
        decision = self.bash("git reset --hard HEAD~1")
        self.assertIsNotNone(decision)
        self.assertEqual(decision[0], "deny")

    def test_denies_recursive_forced_remove_in_chain(self) -> None:
        decision = self.bash("pwd && rm -rf build")
        self.assertIsNotNone(decision)
        self.assertEqual(decision[0], "deny")

    def test_denies_split_and_wrapped_remove_flags(self) -> None:
        for command in ("rm -r -f build", "/bin/rm -Rf build", "command rm -f -r build", "sh -c 'rm -rf build'"):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], "deny")

    def test_denies_xargs_indirected_recursive_remove(self) -> None:
        command = "find build -print0 | xargs -0 rm -rf"
        self.assertEqual(self.bash(command)[0], "deny")

    def test_denies_git_global_option_and_restore_variants(self) -> None:
        for command in (
            "git -C backend reset --hard HEAD",
            "git --work-tree=. clean -fd",
            "git restore README.md",
            "git checkout AGENTS.md",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], "deny")

    def test_denies_forced_git_switch_variants(self) -> None:
        for command in (
            "git checkout -f main",
            "git switch --discard-changes main",
            "git switch -f main",
            "git switch --force main",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], "deny")

    def test_denies_restore_with_short_worktree_flag(self) -> None:
        self.assertEqual(self.bash("git restore -S -W AGENTS.md")[0], "deny")
        self.assertEqual(self.bash("git restore --staged -W AGENTS.md")[0], "deny")

    def test_allows_non_discarding_git_checkout_and_restore(self) -> None:
        self.assertIsNone(self.bash("git checkout -b review-branch"))
        self.assertIsNone(self.bash("git checkout main"))
        self.assertIsNone(self.bash("git checkout feature/foo"))
        self.assertIsNone(self.bash("git checkout release/1.0"))
        self.assertIsNone(self.bash("git restore --staged ordinary.py"))
        self.assertIsNone(self.bash("git restore -S ordinary.py"))

    def test_denies_checkout_of_existing_extensionless_path(self) -> None:
        self.assertEqual(self.bash("git checkout Makefile", ROOT / "backend")[0], "deny")

    def test_asks_for_deploy(self) -> None:
        decision = self.bash("make deploy-backend")
        self.assertIsNotNone(decision)
        self.assertEqual(decision[0], "ask")

    def test_asks_for_make_directory_deploy(self) -> None:
        self.assertEqual(self.bash("make -C backend deploy")[0], "ask")
        self.assertEqual(self.bash("make -C backend deploy-restart")[0], "ask")

    def test_asks_for_dependency_command_variants(self) -> None:
        for command in (
            "npm i package",
            "npm --prefix frontend install package",
            "python -m pip install package",
            "python3.12 -m pip install package",
            "uv pip install package",
            "uv add package",
            "uv remove package",
            "uv --project backend add package",
            "uv --directory backend remove package",
            "poetry add package",
            "corepack pnpm add package",
            "sudo npm install package",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], "ask")

    def test_asks_for_python_module_alembic_revision(self) -> None:
        for command in (
            "python -m alembic revision -m test",
            "python3.12 -m alembic revision -m test",
            "uv run alembic revision -m test",
            "uv --project backend run alembic revision -m test",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], "ask")

    def test_asks_for_production_compose_operation(self) -> None:
        command = "docker compose -f backend/docker-compose.yml up -d"
        self.assertEqual(self.bash(command)[0], "ask")

    def test_asks_for_backend_relative_production_compose(self) -> None:
        command = "docker compose -f docker-compose.yml up -d"
        self.assertEqual(self.bash(command, ROOT / "backend")[0], "ask")

    def test_allows_development_compose_operation(self) -> None:
        command = "docker compose -f docker-compose.dev.yml up -d postgres"
        self.assertIsNone(self.bash(command, ROOT / "backend"))

    def test_asks_for_shell_mutation_of_protected_file(self) -> None:
        decision = self.bash("sed -i '' 's/x/y/' backend/Caddyfile")
        self.assertIsNotNone(decision)
        self.assertEqual(decision[0], "ask")

    def test_asks_for_multi_file_and_long_in_place_edits(self) -> None:
        for command in (
            "sed -i s/x/y/ backend/Caddyfile backend/app/services/example.py",
            "sed --in-place s/x/y/ backend/Caddyfile",
            "perl --in-place -pe s/x/y/ backend/Caddyfile",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command)[0], "ask")

    def test_asks_for_install_to_protected_destination(self) -> None:
        self.assertEqual(self.bash("install /tmp/x backend/Caddyfile")[0], "ask")

    def test_asks_for_alternate_and_multiple_protected_destinations(self) -> None:
        self.assertEqual(self.bash("cp -t backend /tmp/Caddyfile")[0], "ask")
        command = "truncate -s0 backend/Caddyfile backend/app/services/example.py"
        self.assertEqual(self.bash(command)[0], "ask")

    def test_asks_for_relative_protected_path_from_subdirectory(self) -> None:
        decision = self.bash("sed -i '' 's/x/y/' Caddyfile", ROOT / "backend")
        self.assertIsNotNone(decision)
        self.assertEqual(decision[0], "ask")

    def test_allows_reading_protected_file(self) -> None:
        self.assertIsNone(self.bash("sed -n '1,80p' backend/Caddyfile"))

    def test_allows_searching_for_risky_text(self) -> None:
        self.assertIsNone(self.bash("rg 'git reset --hard' docs"))
        self.assertIsNone(self.bash("rg '>' backend/Caddyfile"))

    def test_allows_copying_from_protected_source(self) -> None:
        self.assertIsNone(self.bash("cp backend/Caddyfile /tmp/Caddyfile-copy"))

    def test_asks_for_no_space_redirection_to_protected_file(self) -> None:
        self.assertEqual(self.bash("echo x >backend/Caddyfile")[0], "ask")

    def test_malformed_input_fails_open_without_output(self) -> None:
        result = subprocess.run(
            [sys.executable, str(GUARD_PATH)],
            input="not json",
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_cli_emits_current_pretooluse_contract(self) -> None:
        payload = {
            "tool_name": "Write",
            "cwd": str(ROOT),
            "tool_input": {"file_path": str(ROOT / "backend" / ".env")},
        }
        result = subprocess.run(
            [sys.executable, str(GUARD_PATH)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)},
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        hook_output = output["hookSpecificOutput"]
        self.assertEqual(hook_output["hookEventName"], "PreToolUse")
        self.assertEqual(hook_output["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main(verbosity=2)
