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

import yaml


BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
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


def _root_make_deploy_dry_run() -> str:
    return subprocess.run(
        ["make", "-n", "deploy"],
        cwd=ROOT_DIR,
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


def test_bg_deploy_queues_profile_backfill_after_the_cutover() -> None:
    """Backfill is optional maintenance, never a health/smoke gate."""
    script = _read("bg_deploy.sh")
    flip = script.index("flip_caddy.sh")
    active = script.index('echo "$NEXT" > "$ACTIVE_FILE"')
    backfill = script.index("--profile maintenance up")
    assert flip < active < backfill
    assert "backfill start failed; deployment remains active" in script
    assert "docker compose exec -T -d" not in script


def test_profile_backfill_has_an_observable_dedicated_service() -> None:
    compose = yaml.safe_load((BACKEND_DIR / "docker-compose.yml").read_text())
    service = compose["services"]["oa-profile-backfill"]
    assert service["profiles"] == ["maintenance"]
    assert service["restart"] == "no"
    assert "scripts.backfill_oa_profiles" in service["command"]
    assert service["image"].endswith("${IMAGE_TAG:-latest}")


def test_profile_backfill_make_targets_are_observable() -> None:
    run = _make_target_dry_run("profile-backfill-run")
    status = _make_target_dry_run("profile-backfill-status")
    logs = _make_target_dry_run("profile-backfill-logs")
    assert "--profile maintenance up -d" in run
    assert "State.ExitCode" in status
    assert "logs --tail=100" in logs


def test_backend_fast_deploy_syncs_compose_for_maintenance_service() -> None:
    out = _make_target_dry_run("deploy-restart")
    assert "docker-compose.yml" in out
    assert "bg_deploy.sh" in out


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


# ---------------------------------------------------------------------------
# Rollback path (bg_rollback.sh / `make rollback`). The forward cutover above
# is pinned; these mirror it for the revert path so a future edit cannot
# silently break the ability to roll a bad image back. Every assertion below
# holds against the committed bg_rollback.sh (no script change intended).
# ---------------------------------------------------------------------------


def test_rollback_target_uses_bg_rollback_script() -> None:
    """`make rollback` SCPs bg_rollback.sh + flip_caddy.sh and runs it remotely."""
    out = _make_target_dry_run("rollback")
    assert "bg_rollback.sh" in out
    assert "flip_caddy.sh" in out
    assert "bg_deploy.sh" not in out


def test_rollback_target_does_not_pass_image_tag() -> None:
    """Rollback derives the tag from PREV_TAG; it must not require a fresh build."""
    out = _make_target_dry_run("rollback")
    assert "IMAGE_TAG=" not in out


def test_bg_rollback_requires_recorded_prev_state() -> None:
    """Rollback must refuse to run without a recorded prior deploy (exit 2)."""
    script = _read("bg_rollback.sh")
    assert "PREV_COLOR_FILE" in script
    assert "PREV_TAG_FILE" in script
    assert "exit 2" in script


def test_bg_rollback_recreates_workers_at_prev_tag() -> None:
    """web + workers must move together at PREV_TAG (no image divergence)."""
    script = _read("bg_rollback.sh")
    assert 'IMAGE_TAG="$PREV_TAG"' in script
    assert '--force-recreate "web-$PREV"' in script
    assert "$WORKERS" in script


def test_bg_rollback_stops_backfill_from_demoted_image_before_revive() -> None:
    """Rejected maintenance code must not keep writing after rollback."""
    script = _read("bg_rollback.sh")
    stop = script.index("--profile maintenance stop oa-profile-backfill")
    revive = script.index('--force-recreate "web-$PREV"')
    assert stop < revive


def test_bg_rollback_gates_flip_on_health() -> None:
    """The revived color must be healthy before Caddy is flipped back."""
    script = _read("bg_rollback.sh")
    health = script.index("Health.Status")
    abort = script.index("did not become healthy. ABORTING")
    flip = script.index("flip_caddy.sh")
    assert health < abort < flip
    assert 'if [ "$ok" != "1" ]' in script
    assert "exit 1" in script


def test_bg_rollback_records_demoted_tag_before_swapping_active() -> None:
    """Demoted tag is recorded BEFORE ACTIVE is overwritten, so a mid-swap
    crash leaves rollback still reversible (mirrors bg_deploy's ordering)."""
    script = _read("bg_rollback.sh")
    demoted_tag = script.index("PREV_TAG_FILE")
    active_write = script.index('"$PREV" > "$ACTIVE_FILE"')
    assert demoted_tag < active_write
    assert '"$ACTIVE" > "$PREV_COLOR_FILE"' in script
    assert '"$PREV" > "$ACTIVE_FILE"' in script


def test_bg_rollback_stops_demoted_color() -> None:
    """The demoted color is stopped, not removed (kept for a subsequent rollback)."""
    script = _read("bg_rollback.sh")
    assert 'docker compose stop "web-$ACTIVE"' in script
    assert "docker compose rm" not in script


def test_full_deploy_recreates_the_pushed_frontend() -> None:
    """The full release must serve the frontend image it has just pushed."""
    out = _root_make_deploy_dry_run()
    backend_cutover = out.index("make -C backend deploy")
    frontend_recreate = out.index("make -C backend deploy-restart-frontend")
    assert backend_cutover < frontend_recreate
