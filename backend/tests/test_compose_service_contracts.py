"""Contracts the shipped ``docker-compose.yml`` must keep, asserted against
the file itself (the deploy ships this file, not a rendered copy).

Two classes of regression, both of which reached the droplet silently:

* **SEC-11 — credentials in argv.** Redis credentials were interpolated into
  four ``rq``/``rqscheduler`` commands and into the ``redis`` healthcheck, so
  ``docker inspect`` (and ``ps`` inside the container) handed the broker
  password to anyone who could read the container config. The service now
  takes the broker URL from the environment instead, which ``env_file`` already
  populates. This test walks EVERY service and fails if a credential variable
  ever reappears in ``command`` or ``healthcheck.test`` — not just the four
  services that had the bug, because the redis service's own
  ``--requirepass`` was the same leak in the same file.

* **OPS-24 — an unprobed edge.** ``frontend`` and ``caddy`` carried no
  healthcheck, so the only check on either was a deploy-time script. A frontend
  that booted broken, or a Caddy that failed to load the rendered Caddyfile,
  stayed ``running`` while serving 502s. The probes here must target the
  container's own listener and must accept the status codes that listener
  actually returns.
"""

from __future__ import annotations

from pathlib import Path

import yaml


BACKEND_DIR = Path(__file__).resolve().parents[1]
COMPOSE_FILE = BACKEND_DIR / "docker-compose.yml"

# Variables whose VALUES are credentials. A service may declare them in
# `environment` (that is the supported channel — env_file already does) but
# must never interpolate one into a command or a healthcheck probe.
CREDENTIAL_VARIABLES = ("REDIS_URL", "REDIS_PASSWORD")

# Env var the `scheduler` service must export for `rqscheduler` to reach the
# broker. Unlike `rq`, rqscheduler does NOT read REDIS_URL (its --url flag
# defaults from RQ_REDIS_URL), so dropping `--url` without this would point the
# scheduler at localhost and silently stop every scheduled tick.
SCHEDULER_BROKER_ENV = "RQ_REDIS_URL"


def _services() -> dict:
    document = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    return document["services"]


def _command_text(service: dict) -> str:
    command = service.get("command")
    if command is None:
        return ""
    if isinstance(command, str):
        return command
    return " ".join(str(part) for part in command)


def _healthcheck_text(service: dict) -> str:
    test = (service.get("healthcheck") or {}).get("test")
    if test is None:
        return ""
    if isinstance(test, str):
        return test
    return " ".join(str(part) for part in test)


# --- SEC-11: no credential in argv ------------------------------------------


def test_no_service_leaks_a_redis_credential_into_its_command() -> None:
    offenders = {
        name: _command_text(service)
        for name, service in _services().items()
        if any(f"${{{var}" in _command_text(service) for var in CREDENTIAL_VARIABLES)
    }

    assert not offenders, (
        "redis credentials interpolated into service command(s) — they are "
        f"readable in `docker inspect` and `ps`: {offenders}"
    )


def test_no_service_leaks_a_redis_credential_into_its_healthcheck() -> None:
    offenders = {
        name: _healthcheck_text(service)
        for name, service in _services().items()
        if any(f"${{{var}" in _healthcheck_text(service) for var in CREDENTIAL_VARIABLES)
    }

    assert not offenders, (
        "redis credentials interpolated into healthcheck probe(s) — they are "
        f"readable in `docker inspect`: {offenders}"
    )


def test_broker_workers_take_their_redis_url_from_the_environment() -> None:
    """`rq` falls back to ``os.environ['REDIS_URL']`` when ``--url`` is absent.

    The flag is what put the secret in argv, so it must stay gone — and each
    worker must still declare ``env_file``, which is what supplies the URL.
    """
    workers = ("worker-ingest", "worker-followup", "worker-maintenance")
    services = _services()

    for name in workers:
        assert "--url" not in _command_text(services[name]), (
            f"{name} must not pass --url: it re-exposes the broker password in argv"
        )
        assert services[name].get("env_file"), (
            f"{name} lost env_file; without it rq has no REDIS_URL to fall back to"
        )


def test_scheduler_reaches_redis_via_rq_redis_url_env_not_argv() -> None:
    """rqscheduler reads ``RQ_REDIS_URL``, not ``REDIS_URL``.

    Dropping ``--url`` alone would leave it on its localhost default, silently
    disabling every scheduled tick — so the URL moves into the environment
    under the name the binary actually reads.
    """
    scheduler = _services()["scheduler"]

    assert "--url" not in _command_text(scheduler)
    assert SCHEDULER_BROKER_ENV in (scheduler.get("environment") or {}), (
        "scheduler must export RQ_REDIS_URL; rqscheduler ignores REDIS_URL and "
        "would otherwise connect to localhost"
    )
    assert scheduler.get("env_file"), "scheduler lost env_file (supplies REDIS_URL)"


def test_redis_healthcheck_authenticates_without_the_password_in_argv() -> None:
    """``REDISCLI_AUTH`` is redis-cli's env channel for the password."""
    redis = _services()["redis"]

    assert "REDISCLI_AUTH" in (redis.get("environment") or {}), (
        "redis-cli needs REDISCLI_AUTH once the password leaves argv"
    )
    probe = _healthcheck_text(redis)
    assert "ping" in probe
    assert " -a " not in probe, (
        "`redis-cli -a <password>` puts the credential in the probe's argv"
    )


# --- OPS-24: the edge is probed in-stack -----------------------------------


def test_frontend_has_a_healthcheck_probing_its_own_listener() -> None:
    """nginx serves the SPA on :80; the probe must hit the container itself.

    nginx:alpine ships busybox ``wget`` (verified in the image), so the probe
    needs no dependency the image does not already have.
    """
    healthcheck = _services()["frontend"]["healthcheck"]

    probe = " ".join(str(part) for part in healthcheck["test"])
    assert "127.0.0.1" in probe
    assert "--spider" in probe, "the frontend probe should not download the SPA body"


def test_caddy_healthcheck_accepts_the_redirect_the_edge_actually_returns() -> None:
    """With auto-TLS, Caddy answers ``:80`` with a 308 to ``:443``.

    Treating that as a failure would mark a perfectly healthy edge unhealthy, so
    the probe accepts 200 and 308. It must also stay on the loopback listener:
    busybox ``wget --spider`` follows the 308 to the PUBLIC host, which would
    make the probe depend on public DNS and egress from inside the container.
    """
    healthcheck = _services()["caddy"]["healthcheck"]

    probe = " ".join(str(part) for part in healthcheck["test"])
    assert "127.0.0.1" in probe
    assert "200" in probe and "308" in probe, (
        "the edge answers 308 on :80 under auto-TLS; the probe must accept it"
    )
    assert "-L" not in probe and "wget" not in probe, (
        "the caddy probe must not follow the redirect off the container"
    )


def test_every_healthcheck_declares_the_timing_keys_docker_requires() -> None:
    """Docker ignores an interval/timeout/retries that is absent, not invalid.

    Pinning the four timing keys keeps a new probe consistent with the ones
    already in this file (a typo silently falls back to Docker's 30s default).
    """
    missing = {
        name: sorted(
            {"interval", "timeout", "retries"} - set(service.get("healthcheck") or {})
        )
        for name, service in _services().items()
        if service.get("healthcheck") and not {
            "interval",
            "timeout",
            "retries",
        } <= set(service["healthcheck"])
    }

    assert not missing, f"healthcheck(s) missing required timing keys: {missing}"
