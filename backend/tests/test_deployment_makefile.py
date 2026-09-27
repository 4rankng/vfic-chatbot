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

import json
import re

import os
import subprocess
from pathlib import Path
import textwrap

import pytest
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


def _write_docker_state(path: Path, *, replicas: int, tag: str = "previous-tag") -> None:
    """Seed the stubbed docker's view of the scaled service.

    ``docker compose config`` reports the declared replica count and
    ``compose ps -q`` the live containers, so a sandbox that answers neither
    silently collapses the rolling recreate to its "1 replica" early return and
    the multi-replica path is never executed.
    """
    path.write_text(
        json.dumps(
            {
                "seq": replicas,
                "replicas": {"worker-chatbot": replicas},
                "containers": {
                    "worker-chatbot": [
                        {"cid": f"cid-worker-chatbot-{index}", "tag": tag}
                        for index in range(1, replicas + 1)
                    ]
                },
            }
        ),
        encoding="utf-8",
    )


def _prepare_bg_deploy_sandbox(
    tmp_path: Path,
    *,
    active_color: str | None,
    fail_public_health: bool,
    turn_worker_replicas: int = 3,
    rolled_replica_never_healthy: bool = False,
    fail_turn_pipeline: bool = False,
    missing_post_flip_service: str | None = None,
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

            # The scaled service is answered from a state file: `compose config`
            # reports its declared replica count, `compose ps -q` its live
            # containers, `rm -f` removes one stale container and
            # `compose up --scale` puts one replacement on the new tag — which
            # is what the real orchestrator does between roll steps. Every other
            # service comes from a static table (they are never scaled here).
            state_path = Path(os.environ["VFIC_TEST_STATE"])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            replicas = state["replicas"]
            containers = state["containers"]
            never_healthy = os.environ.get("VFIC_TEST_ROLL_UNHEALTHY") == "1"

            def save():
                state_path.write_text(json.dumps(state), encoding="utf-8")

            service_ps = {
                "web-blue": "cid-web-blue\\n",
                "web-green": "cid-web-green\\n",
                "frontend": "cid-frontend\\n",
                "worker-persistence": "cid-worker-persistence\\n",
                "worker-ingest": "cid-worker-ingest\\n",
                "worker-followup": "cid-worker-followup\\n",
                "worker-maintenance": "cid-worker-maintenance\\n",
                "metrics-watch": "cid-metrics-watch\\n",
                "scheduler": "cid-scheduler\\n",
                "caddy": "cid-caddy\\n",
            }
            images = {
                "cid-web-blue": "franknguyenvd/vfic-backend:test-image",
                "cid-web-green": "franknguyenvd/vfic-backend:previous-tag",
                "cid-frontend": "franknguyenvd/vfic-frontend:test-image",
            }

            if args[:2] == ["compose", "config"]:
                print(json.dumps({
                    "services": {
                        name: {"deploy": {"replicas": count}} for name, count in replicas.items()
                    }
                }))
                raise SystemExit(0)
            if args[:2] == ["compose", "pull"]:
                raise SystemExit(0)
            if args[:2] == ["compose", "up"]:
                scale, values = {}, set()
                for index, arg in enumerate(args):
                    if arg == "--scale":
                        values.add(index + 1)
                        name, _, count = args[index + 1].partition("=")
                        scale[name] = int(count)
                for index, arg in enumerate(args):
                    if index < 2 or arg.startswith("-") or index in values or "=" in arg:
                        continue
                    if arg not in replicas:
                        continue
                    current = containers.setdefault(arg, [])
                    if "--force-recreate" in args:
                        del current[:]
                    while len(current) < scale.get(arg, replicas[arg]):
                        state["seq"] += 1
                        current.append({
                            "cid": "cid-{0}-{1}".format(arg, state["seq"]),
                            "tag": os.environ.get("IMAGE_TAG", ""),
                        })
                save()
                raise SystemExit(0)
            if args[:4] == ["compose", "exec", "-T", "postgres"]:
                if len(args) >= 5 and args[4] == "pg_dump":
                    # Opaque custom-format payload — bg_deploy aborts the deploy
                    # when the pre-migration dump is empty, so it must be non-empty.
                    sys.stdout.write("PGDMP-fake-pre-migration-dump")
                raise SystemExit(0)
            if len(args) >= 4 and args[:3] == ["compose", "ps", "-q"]:
                service = args[3]
                if os.environ.get("VFIC_TEST_MISSING_SERVICE") == service:
                    sys.stdout.write("")  # never created / crashed away
                elif service in containers:
                    sys.stdout.write("".join(e["cid"] + "\\n" for e in containers[service]))
                else:
                    sys.stdout.write(service_ps.get(service, ""))
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
                managed = next(
                    (e for entries in containers.values() for e in entries if e["cid"] == cid),
                    None,
                )
                if managed is not None:
                    if "Health.Status" in fmt:
                        print("unhealthy" if never_healthy else "healthy")
                    elif "RestartCount" in fmt:
                        print("0")
                    elif ".State.Status" in fmt:
                        print("running")
                    elif ".Config.Image" in fmt:
                        print("franknguyenvd/vfic-backend:" + managed["tag"])
                    else:
                        print("")
                    raise SystemExit(0)
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
                    if any("turn_pipeline_check" in arg for arg in args):
                        raise SystemExit(
                            1 if os.environ.get("VFIC_TEST_FAIL_PIPELINE") == "1" else 0
                        )
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
                for service, entries in containers.items():
                    containers[service] = [e for e in entries if e["cid"] not in args[2:]]
                save()
                raise SystemExit(0)

            raise SystemExit(0)
            """
        ),
    )
    state_path = tmp_path / "docker-state.json"
    _write_docker_state(state_path, replicas=turn_worker_replicas)

    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["VFIC_TEST_LOG"] = str(command_log)
    env["VFIC_TEST_STATE"] = str(state_path)
    env["IMAGE_TAG"] = "test-image"
    # `sleep` is stubbed out, so the healthy-budget loop is bounded by its
    # iteration count, not by wall clock: shrink the budget to keep the
    # exhaustion branch cheap to execute.
    env["ROLLING_HEALTH_BUDGET"] = "4"
    if fail_public_health:
        env["VFIC_TEST_FAIL_PUBLIC_HEALTH"] = "1"
    if rolled_replica_never_healthy:
        env["VFIC_TEST_ROLL_UNHEALTHY"] = "1"
    if fail_turn_pipeline:
        env["VFIC_TEST_FAIL_PIPELINE"] = "1"
    if missing_post_flip_service is not None:
        env["VFIC_TEST_MISSING_SERVICE"] = missing_post_flip_service
        # One poll, then give up — the post-flip budget is real wall clock.
        env["POST_FLIP_WAIT_BUDGET"] = "0"

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
    fail_turn_pipeline: bool = False,
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
                "worker-maintenance": "cid-worker-maintenance\\n",
                "metrics-watch": "cid-metrics-watch\\n",
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
                if service.startswith("web-") and command == "python" and args[5] == "-m":
                    if any("turn_pipeline_check" in arg for arg in args):
                        raise SystemExit(
                            1 if os.environ.get("VFIC_TEST_FAIL_PIPELINE") == "1" else 0
                        )
                    raise SystemExit(0)
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
    if fail_turn_pipeline:
        env["VFIC_TEST_FAIL_PIPELINE"] = "1"

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
    # The web color and the non-turn workers are recreated outright; the turn
    # worker is rolled one replica at a time (see
    # test_bg_deploy_rolls_the_turn_worker_one_replica_at_a_time) and must never
    # appear in a blunt force-recreate.
    assert (
        "docker compose up -d --no-deps --force-recreate web-blue"
        " worker-persistence worker-ingest worker-followup scheduler worker-maintenance"
        in commands
    )
    assert not [
        line for line in commands.splitlines() if "--force-recreate" in line and "worker-chatbot" in line
    ]
    assert "docker compose stop web-blue" not in commands
    assert "bash scripts/bg_rollback.sh" not in commands


def test_bg_deploy_rolls_the_turn_worker_one_replica_at_a_time(tmp_path: Path) -> None:
    """The inbound turn queue must keep a live consumer across the roll.

    A single `--force-recreate` of all three replicas strands every accepted
    webhook for the whole cold preload while each container still reports
    healthy (2026-09-26 bot silence), so the sandbox declares 3 replicas and
    asserts the executed command sequence removes exactly one stale container
    at a time, topping the service back up to the declared count between
    removals.
    """
    proc, _root, commands = _prepare_bg_deploy_sandbox(
        tmp_path,
        active_color="green",
        fail_public_health=False,
    )

    lines = commands.splitlines()
    removals = [i for i, line in enumerate(lines) if line.startswith("docker rm -f cid-worker-chatbot-")]
    scale_ups = [
        i
        for i, line in enumerate(lines)
        if line.startswith("docker compose up -d --no-deps --no-recreate --scale worker-chatbot=3")
    ]

    assert proc.returncode == 0
    assert len(removals) == 3, commands
    # A replacement is started (and the count converged back to 3) before the
    # next replica is removed, so at most one consumer is ever down.
    for position, index in enumerate(removals):
        following = removals[position + 1] if position + 1 < len(removals) else len(lines)
        assert any(index < scale_up < following for scale_up in scale_ups), commands
    assert not [line for line in lines if "--force-recreate" in line and "worker-chatbot" in line]
    # The roll converged: three containers, all on the new tag, so the post-flip
    # count check had something to verify.
    final = json.loads((tmp_path / "docker-state.json").read_text(encoding="utf-8"))
    assert [entry["tag"] for entry in final["containers"]["worker-chatbot"]] == ["test-image"] * 3


def test_bg_deploy_aborts_before_the_flip_when_a_rolled_replica_never_turns_healthy(
    tmp_path: Path,
) -> None:
    """A replacement that never registers must not reach the Caddy flip."""
    proc, root, commands = _prepare_bg_deploy_sandbox(
        tmp_path,
        active_color="green",
        fail_public_health=False,
        rolled_replica_never_healthy=True,
    )

    assert proc.returncode == 1
    assert "fewer than 2 healthy worker-chatbot replicas" in proc.stderr
    assert "no healthy worker-chatbot replica before flip" in proc.stderr
    # The flip never ran, so the old color is still the one in the Caddyfile and
    # the recorded active color is untouched.
    assert not (root / "Caddyfile").exists()
    assert not (root / "PREV_COLOR").exists()
    assert (root / "ACTIVE_COLOR").read_text(encoding="utf-8").strip() == "green"
    assert "docker compose stop web-green" not in commands


def test_bg_deploy_rolls_back_when_the_turn_pipeline_gate_fails(tmp_path: Path) -> None:
    """Healthy containers are not proof the queue drains; the gate is."""
    proc, root, commands = _prepare_bg_deploy_sandbox(
        tmp_path,
        active_color="green",
        fail_public_health=False,
        fail_turn_pipeline=True,
    )

    assert proc.returncode == 1
    assert "turn pipeline stalled" in proc.stderr
    assert "POST-FLIP VERIFICATION FAILED" in proc.stderr
    # The flip DID happen, so the only safe exit is the previous color.
    assert "web-blue:8000" in (root / "Caddyfile").read_text(encoding="utf-8")
    assert "bash scripts/bg_rollback.sh" in commands
    assert "docker compose stop web-green" not in commands


@pytest.mark.parametrize("service", ["worker-maintenance", "metrics-watch"])
def test_bg_deploy_post_flip_gate_covers_every_worker_service(tmp_path: Path, service: str) -> None:
    """A worker that never came up must fail the deploy, not ride along green.

    Both services were missing from the post-flip poll: worker-maintenance is
    the component that actually pushes bot replies to Zalo, so a deploy could
    report success while outbound replies silently stopped.
    """
    proc, root, commands = _prepare_bg_deploy_sandbox(
        tmp_path,
        active_color="green",
        fail_public_health=False,
        missing_post_flip_service=service,
    )

    assert proc.returncode == 1
    assert f"service {service} has no running container" in proc.stderr
    assert "POST-FLIP VERIFICATION FAILED" in proc.stderr
    assert "bash scripts/bg_rollback.sh" in commands
    assert "docker compose stop web-green" not in commands
    assert (root / "ACTIVE_COLOR").read_text(encoding="utf-8").strip() == "blue"


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
    # The pre-migration safety dump runs before any migration and lands in the
    # sandbox's pre-migration-dumps directory.
    assert "docker compose exec -T postgres pg_dump -U vfic -Fc -Z6 vfic" in commands
    assert list((root / "pre-migration-dumps").glob("vfic-pre-*.dump"))


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


def test_bg_rollback_exec_failed_turn_pipeline_keeps_state_unswapped(tmp_path: Path) -> None:
    """A stalled pipeline after the revert must abort before the state swap."""
    proc, root, commands = _prepare_bg_rollback_sandbox(
        tmp_path,
        fail_public_health=False,
        fail_turn_pipeline=True,
    )

    assert proc.returncode == 1
    assert "turn pipeline stalled" in proc.stderr
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


BACKEND_IMAGE_PREFIX = "ghcr.io/4rankng/tinghire-be"


def _compose_services() -> dict:
    compose = yaml.safe_load((BACKEND_DIR / "docker-compose.yml").read_text())
    return compose["services"]


def _worker_list(script_name: str) -> list[str]:
    match = re.search(r'^WORKERS="([^"]+)"', _read(script_name), re.MULTILINE)
    assert match is not None, f"{script_name} must define WORKERS"
    return match.group(1).split()


def test_every_backend_service_pinned_to_image_tag_is_deployed() -> None:
    # Found 2026-09-26: worker-maintenance (the outbound dispatcher — the
    # component that actually pushes bot replies to Zalo) was pinned to
    # ${IMAGE_TAG} in compose but missing from WORKERS, so it kept running
    # 38-hour-old code; metrics-watch was never created in production at all.
    # Any backend service pinned to the deploy tag must be deployed by the
    # deploy script, or it silently drifts.
    deployed = set(_worker_list("bg_deploy.sh"))
    missing = set()
    for name, service in _compose_services().items():
        image = str(service.get("image", ""))
        if not image.startswith(BACKEND_IMAGE_PREFIX) or "${IMAGE_TAG" not in image:
            continue
        if name in {"web-blue", "web-green"}:
            continue  # brought up by the flip orchestration itself
        if service.get("profiles"):
            continue  # started explicitly (e.g. oa-profile-backfill post-flip)
        if name not in deployed:
            missing.add(name)

    assert missing == set(), f"services pinned to IMAGE_TAG but never deployed: {missing}"


def test_deploy_and_rollback_worker_lists_agree() -> None:
    assert set(_worker_list("bg_deploy.sh")) == set(_worker_list("bg_rollback.sh"))


# Services this path deliberately never restarts: web-green is the color it
# drains and leaves stopped (blue/green brings it up, deploy-breaking does not),
# and oa-profile-backfill is profile-gated maintenance that runs after a
# successful cutover, not part of the schema swap.
DEPLOY_BREAKING_EXEMPT = {"web-green", "oa-profile-backfill"}


def _compose_service_args(dry_run: str, subcommand: str) -> set[str]:
    line = next(
        line for line in dry_run.splitlines() if f"docker compose {subcommand} " in line
    )
    return set(line.split(f"docker compose {subcommand} ", 1)[1].rstrip('"').split())


def test_deploy_breaking_recreates_every_service_pinned_to_image_tag() -> None:
    # On the breaking-migration path nothing drains the old code, so any
    # ${IMAGE_TAG} service missing from the pull / up lists keeps running a
    # previous release against the schema the migration just changed.
    # worker-maintenance and metrics-watch were both missing (OPS-22).
    dry_run = _make_target_dry_run("deploy-breaking")
    expected = {
        name
        for name, service in _compose_services().items()
        if "${IMAGE_TAG" in str(service.get("image", ""))
    } - DEPLOY_BREAKING_EXEMPT

    for subcommand in ("pull", "up -d --force-recreate"):
        listed = _compose_service_args(dry_run, subcommand)
        assert expected <= listed, f"deploy-breaking {subcommand} omits {expected - listed}"


def test_web_healthcheck_budget_survives_deploy_contention() -> None:
    # A 5s compose timeout with a 3s in-probe socket timeout reported BOTH colors
    # unhealthy during deploy-time CPU contention (2026-09-26), which can abort a
    # deploy mid-cutover. The probe budget must exceed the socket timeout.
    compose = yaml.safe_load((BACKEND_DIR / "docker-compose.yml").read_text())
    for color in ("web-blue", "web-green"):
        healthcheck = compose["services"][color]["healthcheck"]
        assert "timeout=10" in str(healthcheck["test"])
        assert int(str(healthcheck["timeout"]).rstrip("s")) >= 15


def test_chatbot_worker_start_period_covers_the_measured_preload() -> None:
    compose = yaml.safe_load((BACKEND_DIR / "docker-compose.yml").read_text())
    healthcheck = compose["services"]["worker-chatbot"]["healthcheck"]

    # 83.2s measured preload on 2026-09-26; 60s was already optimistic.
    assert int(str(healthcheck["start_period"]).rstrip("s")) >= 180
