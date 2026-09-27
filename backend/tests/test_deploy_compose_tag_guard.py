"""Every host-side ``docker compose`` call must carry IMAGE_TAG (OPS-21).

``backend/docker-compose.yml`` pins every app image to
``${IMAGE_TAG:?IMAGE_TAG is required …}``, and compose interpolates the WHOLE
file for every subcommand — including read-only ``ps``/``logs``/``start`` that
touch no image at all. ``/opt/vfic/.env`` never defines ``IMAGE_TAG`` (nothing
in ``scripts/prod-env.sh`` writes it), so a bare ``docker compose ps`` aborts on
the guard before it runs: ``make backup`` failed 100% of the time, and so did
``make deploy-status``, the three ``profile-backfill-*`` targets and ``make
adminer``.

These tests extract the remote command each target sends and RUN it against a
``docker`` stub that enforces the same guard the real compose file does, so the
invariant is proven by execution rather than by reading the Makefile.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
import textwrap

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent

# The tag the sandbox's "running" web container reports. PREV_TAG in the
# sandbox is deliberately different, so a target that resolved the wrong source
# is caught too.
RUNNING_TAG = "live9f3c"
DUMP_PATH = Path("/tmp/vfic_pg.dump")

# target -> directory whose Makefile defines it
TARGETS = {
    "backup": ROOT_DIR,
    "deploy-status": BACKEND_DIR,
    "profile-backfill-run": BACKEND_DIR,
    "profile-backfill-status": BACKEND_DIR,
    "profile-backfill-logs": BACKEND_DIR,
    "adminer": BACKEND_DIR,
}

_REMOTE_PAYLOAD = re.compile(r"root@bot\.tingting\.vip[ \t\\\n]*'(.*?)'", re.DOTALL)


def _compose_payload(makefile_dir: Path, target: str) -> str:
    """The single-quoted remote command of `make -n <target>` that calls compose."""
    dry_run = subprocess.run(
        ["make", "-n", target],
        cwd=makefile_dir,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    payloads = [
        match for match in _REMOTE_PAYLOAD.findall(dry_run) if "docker compose" in match
    ]
    assert len(payloads) == 1, f"{target}: expected one compose payload, got {payloads}"
    return payloads[0]


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _run_payload(tmp_path: Path, payload: str):
    """Run a remote command locally, with a guard-faithful docker on PATH."""
    root = tmp_path / "opt" / "vfic"
    bin_dir = tmp_path / "bin"
    root.mkdir(parents=True)
    bin_dir.mkdir()
    (root / "ACTIVE_COLOR").write_text("green\n", encoding="utf-8")
    (root / "PREV_TAG").write_text("stale-previous\n", encoding="utf-8")

    command_log = tmp_path / "docker.log"
    _write_executable(
        bin_dir / "docker",
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import os
            import sys
            from pathlib import Path

            args = sys.argv[1:]
            tag = os.environ.get("IMAGE_TAG", "")
            log = Path(os.environ["VFIC_TEST_LOG"])
            with log.open("a", encoding="utf-8") as handle:
                handle.write("IMAGE_TAG=" + (tag or "<unset>") + " docker " + " ".join(args) + "\\n")

            if args[:1] == ["compose"]:
                # `${IMAGE_TAG:?}` interpolates the whole file for every
                # subcommand, so compose aborts before doing anything.
                if not tag:
                    sys.stderr.write(
                        'error: Required variable "IMAGE_TAG" missing a value\\n'
                    )
                    raise SystemExit(1)
                if "ps" in args and "-q" in args and "postgres" in args:
                    print("cid-postgres")
                raise SystemExit(0)
            if args[:2] == ["ps", "-q"]:
                print("cid-web-green")
                raise SystemExit(0)
            if args[:1] == ["inspect"]:
                print("ghcr.io/4rankng/tinghire-be:%s" % os.environ["VFIC_TEST_TAG"])
                raise SystemExit(0)
            if args[:1] == ["exec"]:
                sys.stdout.write("PGDMP-fake-dump")
                raise SystemExit(0)

            raise SystemExit(0)
            """
        ),
    )

    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["VFIC_TEST_LOG"] = str(command_log)
    env["VFIC_TEST_TAG"] = RUNNING_TAG
    env.pop("IMAGE_TAG", None)

    proc = subprocess.run(
        ["/bin/sh", "-c", payload.replace("/opt/vfic", str(root))],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc, command_log.read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clean_dump_path():
    """`make backup` streams the dump to a fixed /tmp path; keep it out of the way."""
    DUMP_PATH.unlink(missing_ok=True)
    yield
    DUMP_PATH.unlink(missing_ok=True)


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_remote_compose_call_carries_the_running_image_tag(tmp_path: Path, target: str) -> None:
    proc, log = _run_payload(tmp_path, _compose_payload(TARGETS[target], target))

    compose_calls = [line for line in log.splitlines() if " docker compose " in line]
    assert proc.returncode == 0, (target, proc.stdout, proc.stderr)
    assert compose_calls, (target, log)
    # The tag comes from the image the ACTIVE color actually runs, not from the
    # recorded previous tag, and it is exported for every compose call.
    assert all(line.startswith(f"IMAGE_TAG={RUNNING_TAG} ") for line in compose_calls), (target, log)
    assert "missing a value" not in proc.stderr, (target, proc.stderr)


def test_backup_dump_runs_only_after_the_guard_is_satisfied(tmp_path: Path) -> None:
    """The dump is the whole point of the target: it must actually be taken."""
    proc, log = _run_payload(tmp_path, _compose_payload(ROOT_DIR, "backup"))

    assert "compose ps -q postgres" in log
    assert "exec cid-postgres pg_dump -U vfic -Fc -Z6" in log, log
    assert DUMP_PATH.read_text(encoding="utf-8") == "PGDMP-fake-dump"
    assert proc.returncode == 0, (proc.stdout, proc.stderr)


def test_profile_backfill_run_starts_the_maintenance_service(tmp_path: Path) -> None:
    """The tag fix must not swallow the target's actual work."""
    payload = _compose_payload(BACKEND_DIR, "profile-backfill-run")
    proc, log = _run_payload(tmp_path, payload)

    assert (
        "compose --profile maintenance up -d --no-deps --force-recreate oa-profile-backfill" in log
    ), log
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
