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

import re

import os
import subprocess
from pathlib import Path
import textwrap

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


def test_bg_deploy_verifies_public_edge_frontend_and_queue_after_flip() -> None:
    """After Caddy flips, the new route must prove public health, frontend, and queue readiness."""
    script = _read("bg_deploy.sh")
    flip = script.index("flip_caddy.sh")
    caddy_route = script.index('assert_caddy_routes_color "$color"')
    public_health = script.index('public_health_body="$(curl -fsS --max-time 15 "$PUBLIC_BASE_URL/health")"')
    post_flip_verify = script.index('if ! verify_post_flip_readiness "$NEXT"; then')
    stop_old = script.index('docker compose stop "web-$ACTIVE"')
    assert flip < post_flip_verify < stop_old
    assert caddy_route < public_health
    assert "https://bot.tingting.vip/health" in script
    assert 'curl -fsS --max-time 15 "https://bot.tingting.vip/"' in script
    assert "http://127.0.0.1:8000/health/queue" in script
    # The expected container count comes from the compose file, never a literal:
    # a hardcoded replica count aborted the 2026-09-22 deploy after the flip when
    # worker-chatbot scaled to 3 (and the same literal broke the rollback check).
    assert 'require_running_service_count "worker-chatbot"' in script
    assert 'require_running_service_count "scheduler"' in script
    assert "declared_replicas" in script
    assert "docker compose config --format json" in script
    assert not re.search(r'require_running_service_count "[a-z-]+" [0-9]', script)


def test_bg_deploy_rolls_back_when_post_flip_verification_fails() -> None:
    """A bad post-flip verification must trigger rollback before the old color is stopped."""
    script = _read("bg_deploy.sh")
    active_write = script.index('echo "$NEXT" > "$ACTIVE_FILE"')
    rollback = script.index(
        'rollback_post_flip_failure "new route failed health/frontend/queue verification"'
    )
    stop_old = script.index('docker compose stop "web-$ACTIVE"')
    assert active_write < rollback < stop_old
    assert "bash scripts/bg_rollback.sh" in script
    assert "POST-FLIP VERIFICATION FAILED" in script


def test_bg_deploy_inaugural_failure_keeps_the_new_color_running_for_operator_intervention() -> None:
    script = _read("bg_deploy.sh")
    assert 'NEXT="blue"' in script
    assert "web-$NEXT stays running and Caddy remains routed there" in script
    assert 'docker compose stop "web-$NEXT"' not in script


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
    # IMAGE_TAG is a required variable on every app service: the mutable
    # :-latest default was exactly the unattended-latest-pull hazard, so the
    # interpolation must fail loudly when the tag is forgotten.
    assert "${IMAGE_TAG:?IMAGE_TAG is required" in service["image"]


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


def test_bg_rollback_verifies_routed_service_before_state_swap() -> None:
    """Rollback must prove the routed previous color before swapping ACTIVE/PREV."""
    script = _read("bg_rollback.sh")
    flip = script.index("flip_caddy.sh")
    verify = script.index('if ! verify_post_flip_readiness "$PREV" "$PREV_TAG"; then')
    swap = script.index('echo "$PREV" > "$ACTIVE_FILE"')
    assert flip < verify < swap
    assert "assert_caddy_routes_color" in script
    assert 'curl -fsS --max-time 15 "$PUBLIC_BASE_URL/health"' in script
    # The expected container count comes from the compose file, never a literal:
    # a hardcoded replica count aborted the 2026-09-22 deploy after the flip when
    # worker-chatbot scaled to 3 (and the same literal broke the rollback check).
    assert 'require_running_service_count "worker-chatbot"' in script
    assert "declared_replicas" in script
    assert not re.search(r'require_running_service_count "[a-z-]+" [0-9]', script)


def test_bg_rollback_failed_verification_keeps_state_unswapped_and_both_colors_running() -> None:
    """A failed rollback verification must exit without swapping files or stopping the demoted color."""
    script = _read("bg_rollback.sh")
    verify = script.index('if ! verify_post_flip_readiness "$PREV" "$PREV_TAG"; then')
    abort = script.index("rollback verification failed; web-$PREV stays running")
    swap = script.index('echo "$ACTIVE" > "$PREV_COLOR_FILE"')
    stop = script.index('docker compose stop "web-$ACTIVE"')
    assert verify < abort < swap < stop
    assert "exit 1" in script


def test_bg_rollback_requires_exactly_one_demoted_container_and_non_empty_tag_before_swap() -> None:
    """Rollback reversibility depends on a unique demoted container and inspected tag."""
    script = _read("bg_rollback.sh")
    demoted = script.index('demoted_cids="$(IMAGE_TAG="$PREV_TAG" docker compose ps -q "web-$ACTIVE"')
    demoted_count = script.index('demoted_count="$(printf \'%s\\n\' "$demoted_cids" | _count_lines)"')
    demoted_img = script.index('demoted_img="$(docker inspect --format \'{{.Config.Image}}\' "$demoted_cid"')
    demoted_tag = script.index('demoted_tag="${demoted_img##*:}"')
    abort = script.index("rollback reversibility check failed;", demoted_tag)
    swap = script.index('echo "$ACTIVE" > "$PREV_COLOR_FILE"')
    assert demoted < demoted_count < demoted_img < demoted_tag < abort < swap
    assert 'if [ "$demoted_count" != "1" ]; then' in script
    assert 'if [ -z "$demoted_img" ] || [ -z "$demoted_tag" ]; then' in script


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


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _prepare_bg_deploy_sandbox(tmp_path: Path, *, active_color: str | None, fail_public_health: bool):
    root = tmp_path / "opt" / "vfic"
    scripts_dir = root / "scripts"
    bin_dir = tmp_path / "bin"
    scripts_dir.mkdir(parents=True)
    bin_dir.mkdir(parents=True)

    for name in ("bg_deploy.sh", "bg_rollback.sh", "flip_caddy.sh"):
        patched = _read(name).replace("/opt/vfic", str(root))
        _write_executable(scripts_dir / name, patched)

    (root / "Caddyfile.template").write_text(
        textwrap.dedent(
            """\
            bot.tingting.vip {
              reverse_proxy __WEB_UPSTREAM__:8000
            }
            """
        ),
        encoding="utf-8",
    )

    if active_color is not None:
        (root / "ACTIVE_COLOR").write_text(active_color, encoding="utf-8")

    command_log = tmp_path / "commands.log"
    _write_executable(
        bin_dir / "sleep",
        "#!/usr/bin/env bash\nexit 0\n",
    )
    _write_executable(
        bin_dir / "bash",
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import os
            import sys
            from pathlib import Path

            log = Path(os.environ["VFIC_TEST_LOG"])
            with log.open("a", encoding="utf-8") as handle:
                handle.write("bash " + " ".join(sys.argv[1:]) + "\\n")

            if len(sys.argv) > 1 and sys.argv[1].endswith("bg_rollback.sh"):
                raise SystemExit(0)

            os.execv("/bin/bash", ["/bin/bash", *sys.argv[1:]])
            """
        ),
    )
    _write_executable(
        bin_dir / "curl",
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import os
            import sys
            from pathlib import Path

            url = sys.argv[-1]
            log = Path(os.environ["VFIC_TEST_LOG"])
            with log.open("a", encoding="utf-8") as handle:
                handle.write(f"curl {url}\\n")

            if url.endswith("/health"):
                if os.environ.get("VFIC_TEST_FAIL_PUBLIC_HEALTH") == "1":
                    raise SystemExit(22)
                print('{"status":"ok"}')
                raise SystemExit(0)
            if url == "https://bot.tingting.vip/":
                print("<html>frontend ok</html>")
                raise SystemExit(0)
            raise SystemExit(0)
            """
        ),
    )
    _write_executable(
        bin_dir / "docker",
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            args = sys.argv[1:]
            log = Path(os.environ["VFIC_TEST_LOG"])
            with log.open("a", encoding="utf-8") as handle:
                handle.write("docker " + " ".join(args) + "\\n")

            service_ps = {
                "web-blue": "cid-web-blue\\n",
                "web-green": "cid-web-green\\n",
                "frontend": "cid-frontend\\n",
                "worker-chatbot": "cid-worker-chatbot-1\\ncid-worker-chatbot-2\\n",
                "worker-persistence": "cid-worker-persistence\\n",
                "worker-ingest": "cid-worker-ingest\\n",
                "worker-followup": "cid-worker-followup\\n",
                "scheduler": "cid-scheduler\\n",
                "caddy": "cid-caddy\\n",
            }
            images = {
                "cid-web-blue": "franknguyenvd/vfic-backend:test-image",
                "cid-web-green": "franknguyenvd/vfic-backend:previous-tag",
                "cid-frontend": "franknguyenvd/vfic-frontend:test-image",
            }

            if args[:2] == ["compose", "pull"]:
                raise SystemExit(0)
            if args[:2] == ["compose", "up"]:
                raise SystemExit(0)
            if args[:4] == ["compose", "exec", "-T", "postgres"]:
                raise SystemExit(0)
            if len(args) >= 4 and args[:3] == ["compose", "ps", "-q"]:
                sys.stdout.write(service_ps.get(args[3], ""))
                raise SystemExit(0)
            if len(args) >= 6 and args[:4] == ["compose", "--profile", "maintenance", "ps"]:
                raise SystemExit(0)
            if len(args) >= 5 and args[:4] == ["compose", "--profile", "maintenance", "logs"]:
                raise SystemExit(0)
            if len(args) >= 5 and args[:4] == ["compose", "--profile", "maintenance", "up"]:
                raise SystemExit(0)
            if len(args) >= 2 and args[0] == "inspect":
                fmt = args[2]
                cid = args[3]
                if "Health.Status" in fmt:
                    print("healthy")
                elif "RestartCount" in fmt:
                    print("0")
                elif ".State.Status" in fmt:
                    print("running")
                elif ".Config.Image" in fmt:
                    print(images.get(cid, "franknguyenvd/vfic-backend:test-image"))
                else:
                    print("")
                raise SystemExit(0)
            if args[:3] == ["compose", "exec", "-T"] and len(args) >= 6:
                service = args[3]
                command = args[4]
                if service.startswith("web-") and command == "python" and args[5] == "-m":
                    raise SystemExit(0)
                if service.startswith("web-") and command == "python" and args[5] == "-":
                    sys.stdin.read()
                    print(json.dumps({"queue_depth": 0, "busy_workers": 0, "total_workers": 5}))
                    raise SystemExit(0)
                if service == "caddy":
                    raise SystemExit(0)
            if args[:2] == ["compose", "stop"]:
                raise SystemExit(0)
            if args[:2] == ["logs", "--tail=40"]:
                raise SystemExit(0)
            if args[:2] == ["rm", "-f"]:
                raise SystemExit(0)

            raise SystemExit(0)
            """
        ),
    )
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["VFIC_TEST_LOG"] = str(command_log)
    env["IMAGE_TAG"] = "test-image"
    if fail_public_health:
        env["VFIC_TEST_FAIL_PUBLIC_HEALTH"] = "1"

    proc = subprocess.run(
        ["/bin/bash", str(scripts_dir / "bg_deploy.sh")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc, root, command_log.read_text(encoding="utf-8")


def _prepare_bg_rollback_sandbox(
    tmp_path: Path,
    *,
    fail_public_health: bool,
    demoted_active_ps: str = "cid-web-green\n",
    demoted_active_image: str = "franknguyenvd/vfic-backend:current-tag",
):
    root = tmp_path / "opt" / "vfic"
    scripts_dir = root / "scripts"
    bin_dir = tmp_path / "bin"
    scripts_dir.mkdir(parents=True)
    bin_dir.mkdir(parents=True)

    for name in ("bg_deploy.sh", "bg_rollback.sh", "flip_caddy.sh"):
        patched = _read(name).replace("/opt/vfic", str(root))
        _write_executable(scripts_dir / name, patched)

    (root / "Caddyfile.template").write_text(
        textwrap.dedent(
            """\
            bot.tingting.vip {
              reverse_proxy __WEB_UPSTREAM__:8000
            }
            """
        ),
        encoding="utf-8",
    )
    (root / "ACTIVE_COLOR").write_text("green\n", encoding="utf-8")
    (root / "PREV_COLOR").write_text("blue\n", encoding="utf-8")
    (root / "PREV_TAG").write_text("previous-tag\n", encoding="utf-8")
    (root / "Caddyfile").write_text("bot.tingting.vip {\n  reverse_proxy web-green:8000\n}\n", encoding="utf-8")

    command_log = tmp_path / "commands.log"
    _write_executable(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(
        bin_dir / "curl",
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import os
            import sys
            from pathlib import Path

            url = sys.argv[-1]
            log = Path(os.environ["VFIC_TEST_LOG"])
            with log.open("a", encoding="utf-8") as handle:
                handle.write(f"curl {url}\\n")

            if url.endswith("/health"):
                if os.environ.get("VFIC_TEST_FAIL_PUBLIC_HEALTH") == "1":
                    raise SystemExit(22)
                print('{"status":"ok"}')
                raise SystemExit(0)
            if url == "https://bot.tingting.vip/":
                print("<html>frontend ok</html>")
                raise SystemExit(0)
            raise SystemExit(0)
            """
        ),
    )
    _write_executable(
        bin_dir / "docker",
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            args = sys.argv[1:]
            log = Path(os.environ["VFIC_TEST_LOG"])
            with log.open("a", encoding="utf-8") as handle:
                handle.write("docker " + " ".join(args) + "\\n")

            service_ps = {
                "web-blue": "cid-web-blue\\n",
                "web-green": os.environ.get("VFIC_TEST_DEMOTED_ACTIVE_PS", "cid-web-green\\n"),
                "frontend": "cid-frontend\\n",
                "worker-chatbot": "cid-worker-chatbot-1\\ncid-worker-chatbot-2\\n",
                "worker-persistence": "cid-worker-persistence\\n",
                "worker-ingest": "cid-worker-ingest\\n",
                "worker-followup": "cid-worker-followup\\n",
                "scheduler": "cid-scheduler\\n",
                "caddy": "cid-caddy\\n",
                "oa-profile-backfill": "cid-backfill\\n",
            }
            images = {
                "cid-web-blue": "franknguyenvd/vfic-backend:previous-tag",
                "cid-web-green": os.environ.get("VFIC_TEST_DEMOTED_ACTIVE_IMAGE", "franknguyenvd/vfic-backend:current-tag"),
                "cid-frontend": "franknguyenvd/vfic-frontend:test-image",
            }

            if args[:2] == ["compose", "up"]:
                raise SystemExit(0)
            if len(args) >= 4 and args[:3] == ["compose", "ps", "-q"]:
                sys.stdout.write(service_ps.get(args[3], ""))
                raise SystemExit(0)
            if len(args) >= 5 and args[:4] == ["compose", "--profile", "maintenance", "stop"]:
                raise SystemExit(0)
            if len(args) >= 2 and args[0] == "inspect":
                fmt = args[2]
                cid = args[3]
                if "Health.Status" in fmt:
                    print("healthy")
                elif "RestartCount" in fmt:
                    print("0")
                elif ".State.Status" in fmt:
                    print("running")
                elif ".Config.Image" in fmt:
                    print(images.get(cid, "franknguyenvd/vfic-backend:previous-tag"))
                else:
                    print("")
                raise SystemExit(0)
            if args[:3] == ["compose", "exec", "-T"] and len(args) >= 6:
                service = args[3]
                command = args[4]
                if service.startswith("web-") and command == "python" and args[5] == "-":
                    sys.stdin.read()
                    print(json.dumps({"queue_depth": 0, "busy_workers": 0, "total_workers": 5}))
                    raise SystemExit(0)
                if service == "caddy":
                    raise SystemExit(0)
            if args[:2] == ["compose", "stop"]:
                raise SystemExit(0)

            raise SystemExit(0)
            """
        ),
    )

    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["VFIC_TEST_LOG"] = str(command_log)
    env["VFIC_TEST_DEMOTED_ACTIVE_PS"] = demoted_active_ps
    env["VFIC_TEST_DEMOTED_ACTIVE_IMAGE"] = demoted_active_image
    if fail_public_health:
        env["VFIC_TEST_FAIL_PUBLIC_HEALTH"] = "1"

    proc = subprocess.run(
        ["/bin/bash", str(scripts_dir / "bg_rollback.sh")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc, root, command_log.read_text(encoding="utf-8")


def test_bg_deploy_exec_inaugural_public_verify_failure_keeps_blue_running(tmp_path: Path) -> None:
    proc, root, commands = _prepare_bg_deploy_sandbox(
        tmp_path,
        active_color=None,
        fail_public_health=True,
    )

    assert proc.returncode == 1
    assert (root / "ACTIVE_COLOR").read_text(encoding="utf-8").strip() == "blue"
    assert "web-blue:8000" in (root / "Caddyfile").read_text(encoding="utf-8")
    assert "docker compose up -d --no-deps --force-recreate web-blue worker-chatbot worker-persistence worker-ingest worker-followup scheduler" in commands
    assert "docker compose stop web-blue" not in commands
    assert "bash scripts/bg_rollback.sh" not in commands


def test_bg_deploy_exec_success_stops_old_color_only_after_public_checks(tmp_path: Path) -> None:
    proc, root, commands = _prepare_bg_deploy_sandbox(
        tmp_path,
        active_color="green",
        fail_public_health=False,
    )

    assert proc.returncode == 0
    assert (root / "ACTIVE_COLOR").read_text(encoding="utf-8").strip() == "blue"
    assert (root / "PREV_COLOR").read_text(encoding="utf-8").strip() == "green"
    assert "web-blue:8000" in (root / "Caddyfile").read_text(encoding="utf-8")
    assert commands.index("curl https://bot.tingting.vip/health\n") < commands.index(
        "docker compose stop web-green\n"
    )
    assert "docker compose stop web-green" in commands


def test_bg_rollback_exec_failed_public_verify_keeps_state_unswapped(tmp_path: Path) -> None:
    proc, root, commands = _prepare_bg_rollback_sandbox(
        tmp_path,
        fail_public_health=True,
    )

    assert proc.returncode == 1
    assert (root / "ACTIVE_COLOR").read_text(encoding="utf-8").strip() == "green"
    assert (root / "PREV_COLOR").read_text(encoding="utf-8").strip() == "blue"
    assert (root / "PREV_TAG").read_text(encoding="utf-8").strip() == "previous-tag"
    assert "web-blue:8000" in (root / "Caddyfile").read_text(encoding="utf-8")
    assert "docker compose stop web-green" not in commands


def test_bg_rollback_exec_missing_demoted_container_keeps_state_unswapped(tmp_path: Path) -> None:
    proc, root, commands = _prepare_bg_rollback_sandbox(
        tmp_path,
        fail_public_health=False,
        demoted_active_ps="",
    )

    assert proc.returncode == 1
    assert (root / "ACTIVE_COLOR").read_text(encoding="utf-8").strip() == "green"
    assert (root / "PREV_COLOR").read_text(encoding="utf-8").strip() == "blue"
    assert (root / "PREV_TAG").read_text(encoding="utf-8").strip() == "previous-tag"
    assert "docker compose stop web-green" not in commands


def test_bg_rollback_exec_empty_demoted_tag_keeps_state_unswapped(tmp_path: Path) -> None:
    proc, root, commands = _prepare_bg_rollback_sandbox(
        tmp_path,
        fail_public_health=False,
        demoted_active_image="",
    )

    assert proc.returncode == 1
    assert (root / "ACTIVE_COLOR").read_text(encoding="utf-8").strip() == "green"
    assert (root / "PREV_COLOR").read_text(encoding="utf-8").strip() == "blue"
    assert (root / "PREV_TAG").read_text(encoding="utf-8").strip() == "previous-tag"
    assert "docker compose stop web-green" not in commands


def test_bg_rollback_exec_success_swaps_state_only_after_public_checks(tmp_path: Path) -> None:
    proc, root, commands = _prepare_bg_rollback_sandbox(
        tmp_path,
        fail_public_health=False,
    )

    assert proc.returncode == 0
    assert (root / "ACTIVE_COLOR").read_text(encoding="utf-8").strip() == "blue"
    assert (root / "PREV_COLOR").read_text(encoding="utf-8").strip() == "green"
    assert (root / "PREV_TAG").read_text(encoding="utf-8").strip() == "current-tag"
    assert "web-blue:8000" in (root / "Caddyfile").read_text(encoding="utf-8")
    assert commands.index("curl https://bot.tingting.vip/health\n") < commands.index(
        "docker compose stop web-green\n"
    )
