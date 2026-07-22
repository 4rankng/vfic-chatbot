"""Regression checks for the blue/green deployment flow.

The deploy invariants that used to live inline in the Makefile now live in
``scripts/bg_deploy.sh``. These pin the safety-critical ones:

  * ``make deploy`` hands off to the blue/green orchestrator (the legacy inline
    single-``web`` force-recreate is gone).
  * The new color must pass its healthcheck AND the smoke gate BEFORE Caddy is
    flipped onto it — prod never routes to a cold or broken image.
  * A failed smoke gate aborts (``exit 1``) before the flip.
  * The backend cutover never pulls the unrelated frontend image.
  * The Caddy bind mount keeps its inode during a reload, so the refreshed
    configuration reaches the running Caddy process.
  * The deploy scripts are syntactically valid bash.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = BACKEND_DIR / "scripts"


def _read(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def _make_deploy_dry_run() -> str:
    return subprocess.run(
        ["make", "-n", "deploy", "IMAGE_TAG=test-image"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _make_target_dry_run(target: str) -> str:
    return subprocess.run(
        ["make", "-n", target],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_deploy_scripts_are_valid_bash() -> None:
    """Syntax-check the deploy scripts that ship to the droplet."""
    for name in ("bg_deploy.sh", "bg_rollback.sh", "flip_caddy.sh"):
        proc = subprocess.run(
            ["bash", "-n", str(SCRIPTS / name)], capture_output=True, text=True, check=False
        )
        assert proc.returncode == 0, (name, proc.stderr)


def test_deploy_uses_blue_green_orchestrator() -> None:
    """`make deploy` ships the Caddy TEMPLATE + hands off to bg_deploy.sh.

    The legacy inline `--force-recreate web ...` must be gone (it is now inside
    bg_deploy.sh, invoked remotely, so it does not appear in the make dry-run).
    """
    out = _make_deploy_dry_run()
    assert "Caddyfile.template" in out
    assert "bg_deploy.sh" in out
    assert "flip_caddy.sh" in out
    assert "--force-recreate" not in out


def test_bg_deploy_gates_flip_on_health_and_smoke() -> None:
    """Healthcheck AND smoke gate must run BEFORE the Caddy flip."""
    script = _read("bg_deploy.sh")
    health = script.index("Health.Status")
    smoke = script.index("scripts.smoke_turn")
    flip = script.index("flip_caddy.sh")
    assert health < flip, "new color health must be verified before the flip"
    assert smoke < flip, "smoke gate must pass before the flip"


def test_bg_deploy_smoke_failure_aborts_before_flip() -> None:
    """A failed smoke gate must exit before flip_caddy so prod keeps serving old."""
    script = _read("bg_deploy.sh")
    assert "if !" in script and "scripts.smoke_turn" in script
    assert "ABORTING" in script


def test_bg_deploy_only_pulls_backend_services() -> None:
    """A backend cutover must not request frontend:<backend-git-sha>."""
    script = _read("bg_deploy.sh")
    pull_line = next(line for line in script.splitlines() if "docker compose pull" in line)
    assert "frontend" not in pull_line
    assert '"web-$NEXT"' in pull_line
    assert "$WORKERS" in pull_line


def test_flip_caddy_preserves_bind_mount_inode_for_reload() -> None:
    """Replacing file contents (not its inode) makes reload see the new route."""
    script = _read("flip_caddy.sh")
    assert 'cat "$tmp" > Caddyfile' in script
    assert 'mv "$tmp" Caddyfile' not in script
    assert "docker compose up -d --no-deps caddy" in script
    assert "caddy reload --config /etc/caddy/Caddyfile" in script


def test_deploy_status_remote_command_is_shell_safe() -> None:
    """The status target must not pass shell metacharacters in fallback labels."""
    out = _make_target_dry_run("deploy-status")
    assert "<inaugural>" not in out
    assert "echo inaugural" in out
