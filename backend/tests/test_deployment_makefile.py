"""Regression checks for deployment command quoting."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _deploy_command(marker: str) -> str:
    result = subprocess.run(
        ["make", "-n", "deploy", "IMAGE_TAG=test-image"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    return next(line for line in result.stdout.splitlines() if marker in line)


def _capture_remote_script(command: str, tmp_path: Path) -> str:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    captured_args = tmp_path / "ssh-args.json"
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import os\n"
        "from pathlib import Path\n"
        "import sys\n"
        'Path(os.environ["CAPTURED_SSH_ARGS"]).write_text(json.dumps(sys.argv[1:]))\n',
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
    fake_docker = fake_bin / "docker"
    fake_docker.write_text("#!/bin/sh\nprintf 'local-docker-expansion\\n'\n", encoding="utf-8")
    fake_docker.chmod(0o755)
    environment = {
        **os.environ,
        "CAPTURED_SSH_ARGS": str(captured_args),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    }

    subprocess.run(
        command,
        cwd=BACKEND_DIR,
        env=environment,
        shell=True,
        executable="/bin/bash",
        check=True,
    )

    arguments = json.loads(captured_args.read_text(encoding="utf-8"))
    return arguments[-1]


def test_deploy_health_check_preserves_remote_retry_loop(tmp_path: Path) -> None:
    remote_script = _capture_remote_script(_deploy_command("urlopen"), tmp_path)

    assert "$(seq 1 50)" in remote_script
    syntax = subprocess.run(
        ["bash", "-n", "-c", remote_script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr


def test_deploy_container_check_preserves_remote_substitutions(tmp_path: Path) -> None:
    remote_script = _capture_remote_script(_deploy_command("docker inspect"), tmp_path)

    # Each service may have multiple replicas (worker-chatbot runs replicas: 2),
    # so the loop must iterate over every container ID returned by `ps -q`,
    # not treat the (possibly multi-line) blob as a single container name.
    assert 'containers=$(docker compose ps -q "$service")' in remote_script
    assert '[ -n "$containers" ] || exit 1' in remote_script
    assert 'for container in $containers; do' in remote_script
    assert '$(docker inspect --format "{{.State.Status}}" "$container")' in remote_script
