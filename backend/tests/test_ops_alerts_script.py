"""Executed coverage for the host-side alert sweep (``scripts/ops-alerts.sh``).

The script runs from cron, where the working directory is not ``/opt/vfic`` and
the environment carries no ``IMAGE_TAG``. Both facts broke its two docker
checks in ways no amount of reading the source reveals:

  * ``docker compose exec`` without ``IMAGE_TAG`` aborts on the prod compose
    file's ``${IMAGE_TAG:?}`` guard, so ``/metrics`` was never read and the
    check could only ever say "could not read /metrics".
  * ``ACTIVE_COLOR`` was read relative to the cwd, so the check probed the
    *idle* colour after a cutover.
  * ``numfmt --from=iec`` cannot parse docker's "12.34GB (67%)" reclaimable
    string, so the >10GB disk-pressure warn was unreachable.

These tests run the real script against a stubbed ``docker``/``curl``/``df`` on
PATH, from a working directory that is deliberately NOT ``/opt/vfic``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
import textwrap

import pytest


ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPT = ROOT_DIR / "scripts" / "ops-alerts.sh"

HEALTHY_METRICS = """\
chat_queue_max_depth 500
webhook_high_depth 3
busy_workers 1
total_workers 5
reconcile_enqueue_failed_total 0
reconcile_unknown_send_outcome 0
"""

SATURATED_METRICS = """\
chat_queue_max_depth 500
webhook_high_depth 400
busy_workers 5
total_workers 5
reconcile_enqueue_failed_total 7
"""


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _run_ops_alerts(
    tmp_path: Path,
    *,
    active_color: str | None,
    metrics: str = HEALTHY_METRICS,
    docker_df: str = '{"Type":"Images","Reclaimable":"1.2GB (30%)"}',
    running_web: bool = True,
):
    """Run the script from a cron-like cwd with a guard-faithful docker stub."""
    root = tmp_path / "opt" / "vfic"
    bin_dir = tmp_path / "bin"
    root.mkdir(parents=True)
    bin_dir.mkdir()

    if active_color is not None:
        (root / "ACTIVE_COLOR").write_text(active_color, encoding="utf-8")

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

            if args[:2] == ["system", "df"]:
                sys.stdout.write(os.environ.get("VFIC_TEST_DOCKER_DF", ""))
                raise SystemExit(0)
            if args[:2] == ["ps", "-q"]:
                if os.environ.get("VFIC_TEST_NO_WEB") == "1":
                    raise SystemExit(0)
                print("cid-web-active")
                raise SystemExit(0)
            if args[:1] == ["inspect"]:
                print("ghcr.io/4rankng/tinghire-be:9f3c1ab")
                raise SystemExit(0)
            if args[:1] == ["compose"] and "exec" in args:
                # The prod compose file aborts EVERY subcommand on an unset
                # IMAGE_TAG (`${IMAGE_TAG:?}`), whatever the subcommand is.
                if not tag:
                    sys.stderr.write(
                        'error: Required variable "IMAGE_TAG" is missing a value\\n'
                    )
                    raise SystemExit(1)
                sys.stdout.write(os.environ.get("VFIC_TEST_METRICS", ""))
                raise SystemExit(0)

            raise SystemExit(0)
            """
        ),
    )
    _write_executable(bin_dir / "curl", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(
        bin_dir / "df",
        "#!/usr/bin/env bash\nprintf 'Filesystem 1K-blocks Used Available Use%% Mounted on\\n/dev/disk3 100 20 80 20%% /\\n'\n",
    )

    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["VFIC_TEST_LOG"] = str(command_log)
    env["VFIC_TEST_METRICS"] = metrics
    env["VFIC_TEST_DOCKER_DF"] = docker_df
    if not running_web:
        env["VFIC_TEST_NO_WEB"] = "1"

    script = SCRIPT.read_text(encoding="utf-8").replace("/opt/vfic", str(root))
    sandbox_script = tmp_path / "ops-alerts.sh"
    _write_executable(sandbox_script, script)

    # cwd is the tmp root, never the stack directory: that is the cron case.
    proc = subprocess.run(
        ["/bin/bash", str(sandbox_script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc, command_log.read_text(encoding="utf-8")


def test_metrics_probe_reads_the_active_color_from_the_absolute_path(tmp_path: Path) -> None:
    """After a cutover the probe must follow ACTIVE_COLOR, not default to blue."""
    proc, log = _run_ops_alerts(
        tmp_path,
        active_color="green",
        metrics=SATURATED_METRICS,
    )

    assert "exec -T web-green" in log, log
    assert "web-blue" not in log, log
    # The saturated payload was actually parsed, so /metrics was read end to end.
    assert "webhook_high depth 400" in proc.stderr
    assert proc.returncode == 0


def test_metrics_probe_exports_the_tag_the_active_color_runs(tmp_path: Path) -> None:
    """The compose call must carry the running image tag or the guard kills it."""
    _proc, log = _run_ops_alerts(tmp_path, active_color="blue")

    compose_calls = [line for line in log.splitlines() if " compose " in line]
    assert compose_calls, log
    assert all(line.startswith("IMAGE_TAG=9f3c1ab ") for line in compose_calls), log


def test_metrics_probe_reports_the_failure_when_the_container_is_unreadable(
    tmp_path: Path,
) -> None:
    """A genuinely unreadable /metrics must still warn rather than pass silently."""
    proc, _log = _run_ops_alerts(tmp_path, active_color="blue", metrics="")

    assert "could not read /metrics from web-blue" in proc.stderr


def test_metrics_probe_survives_a_missing_active_color(tmp_path: Path) -> None:
    """No ACTIVE_COLOR file (fresh droplet): fall back, do not abort the run."""
    proc, log = _run_ops_alerts(tmp_path, active_color=None)

    assert "exec -T web-blue" in log, log
    assert "could not read /metrics" not in proc.stderr
    assert proc.returncode == 0


def test_metrics_probe_survives_no_running_web_container(tmp_path: Path) -> None:
    """The stack is down: the tag falls back to PREV_TAG, the probe still runs."""
    proc, log = _run_ops_alerts(tmp_path, active_color="blue", running_web=False)

    compose_calls = [line for line in log.splitlines() if " compose " in line]
    assert compose_calls, log
    # PREV_TAG is absent in the sandbox too, so the placeholder is used — the
    # point is that the guard is satisfied and the script does not abort.
    assert all(line.startswith("IMAGE_TAG=unknown ") for line in compose_calls), log
    assert proc.returncode == 0


@pytest.mark.parametrize(
    ("docker_df", "expected_warning"),
    [
        ('{"Type":"Images","Reclaimable":"12.34GB (67%)"}', True),
        (
            '{"Type":"Images","Reclaimable":"6GB (10%)"}\n'
            '{"Type":"Containers","Reclaimable":"5GB (40%)"}',
            True,
        ),
        ('{"Type":"Images","Reclaimable":"1.2GB (30%)"}', False),
        ("", False),
    ],
)
def test_docker_reclaimable_warns_above_ten_gigabytes(
    tmp_path: Path, docker_df: str, expected_warning: bool
) -> None:
    """docker's reclaimable field is a human string, not a number."""
    proc, _log = _run_ops_alerts(tmp_path, active_color="blue", docker_df=docker_df)

    warned = "docker reclaimable" in proc.stderr
    assert warned is expected_warning, proc.stderr
    assert proc.returncode == 0


def test_docker_reclaimable_ignores_unparseable_rows(tmp_path: Path) -> None:
    """A version that prints something else must not crash the sweep."""
    proc, _log = _run_ops_alerts(
        tmp_path,
        active_color="blue",
        docker_df="not json at all\n",
    )

    assert "docker reclaimable" not in proc.stderr
    assert proc.returncode == 0


def test_script_reports_a_clean_run_on_stdout(tmp_path: Path) -> None:
    proc, _log = _run_ops_alerts(tmp_path, active_color="blue")

    assert proc.stdout.strip().endswith("ok")
    assert proc.stderr == ""
