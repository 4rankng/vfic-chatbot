"""Routing checks remain portable without weakening tracked source validation."""

from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _check(tmp_path: Path, instructions: str, *, local_file: bool = False):
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(
        REPO_ROOT / "scripts/check-doc-links.mjs", tmp_path / "scripts/check-doc-links.mjs"
    )
    (tmp_path / "standards").mkdir()
    for name in ("agent-completion-checklist.md", "definition-of-done.md", "review-checklist.md"):
        (tmp_path / "standards" / name).write_text("# Tracked instructions\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(instructions, encoding="utf-8")
    (tmp_path / "Makefile").write_text("check:\n\ttrue\n", encoding="utf-8")
    if local_file:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude/CLAUDE.md").write_text("local only", encoding="utf-8")
    return subprocess.run(
        ["node", "scripts/check-doc-links.mjs"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_routing_guard_accepts_a_description_of_the_untracked_directory(tmp_path):
    result = _check(tmp_path, "`.claude/` is machine-local. Run `make check`.\n")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("local_file", [False, True])
def test_routing_guard_rejects_routes_into_local_instructions(tmp_path, local_file):
    result = _check(tmp_path, "Read `.claude/CLAUDE.md`.\n", local_file=local_file)
    assert result.returncode == 1
    assert "routes into machine-local instructions" in result.stderr


@pytest.mark.parametrize("instructions", ["Read `docs/missing.md`.\n", "Run `make missing`.\n"])
def test_routing_guard_still_rejects_missing_tracked_sources_and_commands(tmp_path, instructions):
    result = _check(tmp_path, instructions)
    assert result.returncode == 1
    assert "Release blocked" in result.stderr
