"""The container model ``docker compose config`` produces for this stack.

Shared by the tests that assert against what the deploy will actually run. The
deploy ships ``docker-compose.yml`` to the droplet, so what runs is never the
YAML text: it is compose's rendered model — variables interpolated, every
service's ``env_file`` folded into its environment, ``$$`` turned back into the
literal ``$`` a process in the container sees.

Rendering needs the compose CLI but not a daemon (``docker compose config`` is a
pure parse + interpolate), and it runs against a synthetic ``.env`` built from
the keys ``.env.example`` documents, so nothing built on this reads — or prints —
a developer's real credentials.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
COMPOSE_FILE = BACKEND_DIR / "docker-compose.yml"
ENV_EXAMPLE = BACKEND_DIR / ".env.example"

# The synthetic deployment the render produces. The broker is addressed by its
# compose service name, so a service whose broker URL stopped resolving to the
# broker cannot accidentally agree with an assertion about reaching it. One
# fixed password, because a test that checks *which* credential a container
# would use is only meaningful when every credential in the world is known.
BROKER_SERVICE = "redis"
BROKER_PORT = 6379
BROKER_DB = 0
SYNTHETIC_PASSWORD = "synthetic-redis-password"
SYNTHETIC_BROKER_URL = f"redis://:{SYNTHETIC_PASSWORD}@{BROKER_SERVICE}:{BROKER_PORT}/{BROKER_DB}"

# Values compose interpolates from the host environment, or aborts on. Every one
# of them is synthetic, so the render can neither depend on nor absorb a value
# the machine running the tests happens to export.
INTERPOLATED = {
    "IMAGE_TAG": "contract-render",
    "POSTGRES_USER": "vfic",
    "POSTGRES_PASSWORD": "synthetic-postgres-password",
    "POSTGRES_DB": "vfic",
    "REDIS_PASSWORD": SYNTHETIC_PASSWORD,
    "REDIS_URL": SYNTHETIC_BROKER_URL,
}

# redis-cli's documented environment channel for the password. The rendered
# redis healthcheck argv names no credential at all — the client picks this
# variable up from the service's own environment.
REDIS_CLIENT_AUTH_ENV = "REDISCLI_AUTH"

# Host environment the compose CLI itself needs, passed through deliberately
# rather than inheriting ``os.environ``: a REDIS_URL exported by the developer
# must not be able to satisfy the render.
_CLI_ENV_PASSTHROUGH = (
    "PATH",
    "HOME",
    "TMPDIR",
    "DOCKER_HOST",
    "DOCKER_CONFIG",
    "DOCKER_CONTEXT",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
    "XDG_CONFIG_HOME",
    "XDG_RUNTIME_DIR",
)


def compose_cli() -> list[str] | None:
    """The compose CLI, or None when this machine cannot render with it."""
    if shutil.which("docker") is None:
        return None
    probe = subprocess.run(
        ["docker", "compose", "version"], capture_output=True, text=True, check=False
    )
    return ["docker", "compose"] if probe.returncode == 0 else None


def synthetic_env_file() -> str:
    """A ``.env`` carrying every key ``.env.example`` documents.

    The services with ``env_file: .env`` resolve it against the project the
    render runs in, so this is what supplies the workers' ``REDIS_URL``. Values
    are synthetic, and the broker URL and its password are the ones the
    resolution tests check for, so a probe whose variable is missing from a
    service's environment fails instead of quietly matching whatever the
    developer has locally.
    """
    keys = [
        line.split("=", 1)[0]
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if re.match(r"^[A-Z][A-Z0-9_]*=", line)
    ]
    values = {key: f"synthetic-{key.lower().replace('_', '-')}" for key in keys}
    values["REDIS_PASSWORD"] = SYNTHETIC_PASSWORD
    values["REDIS_URL"] = SYNTHETIC_BROKER_URL
    return "".join(f"{key}={values[key]}\n" for key in keys)


def render_services(project: Path, cli: list[str], source: Path = COMPOSE_FILE) -> dict:
    """Run ``docker compose config`` over ``source`` and return its service model."""
    compose = project / COMPOSE_FILE.name
    compose.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (project / ".env").write_text(synthetic_env_file(), encoding="utf-8")
    # The edge mounts this read-only; an empty file is enough to render.
    (project / "Caddyfile").write_text("", encoding="utf-8")

    environment = {key: os.environ[key] for key in _CLI_ENV_PASSTHROUGH if key in os.environ}
    environment.update(INTERPOLATED)
    completed = subprocess.run(
        [*cli, "-f", str(compose), "config", "--format", "json"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"{source} does not render, so every host-side `docker compose` call on the droplet "
        f"aborts before it does anything: {completed.stderr}"
    )
    return json.loads(completed.stdout)["services"]


def container_environment(service: dict) -> dict[str, str]:
    """The environment the container is started with.

    compose has already folded every ``env_file`` in and drops variables that
    resolve to nothing, so this is the complete set the process can read.
    """
    return {
        key: value
        for key, value in (service.get("environment") or {}).items()
        if value is not None
    }


def effective_argv(service: dict, section: str) -> tuple[str, ...]:
    """The argv the container's process for ``section`` is started with.

    ``command`` is exec'd as written. A healthcheck is either an exec form
    (``CMD``) or a shell form (``CMD-SHELL``), which the daemon runs as
    ``/bin/sh -c <script>``; a probe is best analysed the way it will be
    interpreted. compose's ``$$`` escape reaches the container as a single
    ``$``, so it is undone here — after this call every string is one a process
    in the container would actually see.
    """
    if section == "command":
        raw = service.get("command")
        parts = shlex.split(raw) if isinstance(raw, str) else list(raw or ())
    else:
        test = (service.get("healthcheck") or {}).get("test")
        parts = shlex.split(test) if isinstance(test, str) else list(test or ())
        if parts:
            form, *rest = parts
            if form == "CMD":
                parts = rest
            elif form == "CMD-SHELL":
                parts = ["/bin/sh", "-c", *rest]
            elif form == "NONE":
                parts = []
    return tuple(str(part).replace("$$", "$") for part in parts)
