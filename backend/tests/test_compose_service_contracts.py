"""Contracts the shipped ``docker-compose.yml`` must keep, asserted against the
container definitions compose actually renders.

The deploy ships this file to the droplet, so what runs is never the YAML text —
it is compose's *rendered* model: variables interpolated, every service's
``env_file`` folded into its environment, ``$$`` turned back into the literal
``$`` a process in the container sees. These tests read that model and assert
properties of the container it produces: a probe pointed at a port the service
does not serve, a worker whose broker URL resolves to localhost because the
variable it reads is gone, a credential sitting in a process list. Grepping the
YAML proves none of those — ``"200" in probe`` stays green for a probe that
probes the wrong thing, and a bound like ``0 < floor <= 100`` is satisfied by
values with no teeth.

The render itself, and the synthetic project it runs in, live in
``tests/helpers/compose_model.py``; whether each probe can actually go *red* is
proved by execution in ``test_compose_probe_runtime.py``.

Two regressions these pin, both of which reached the droplet silently:

* **SEC-11 — credentials in argv.** Redis credentials were interpolated into
  four ``rq``/``rqscheduler`` commands and into the ``redis`` healthcheck, so
  ``docker inspect`` (and ``ps`` inside the container) handed the broker
  password to anyone who could read the container config. Compose's rendered
  argv *is* what lands in that config, so it is the right surface to assert on:
  an argv element equal to a credential value is a leak, in any service.

* **OPS-24 — an unprobed edge.** ``frontend`` and ``caddy`` carried no
  healthcheck, so a frontend that booted broken, or a Caddy that failed to load
  the rendered Caddyfile, stayed ``running`` while serving 502s. A probe only
  helps if it can go red, so the property that matters is not "a probe exists"
  but "the endpoint the probe names is one this service actually serves, on the
  container itself". Whether the probe exits non-zero against a broken listener
  is proved by execution, in ``test_compose_probe_runtime.py``.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests.helpers.compose_model import (
    BROKER_DB,
    BROKER_PORT,
    BROKER_SERVICE,
    REDIS_CLIENT_AUTH_ENV,
    SYNTHETIC_PASSWORD,
    compose_cli,
    container_environment,
    effective_argv,
    render_services,
)

# Services whose healthcheck reaches an HTTP endpoint. Kept explicit so the
# probe audits have a declared scope, and pinned by
# ``test_the_probed_http_services_are_the_ones_under_audit`` so a new
# healthchecking service cannot slip past them.
AUDITED_HTTP_SERVICES = ("web-blue", "web-green", "frontend", "caddy")

# Environment variables whose values are credentials. Matched on the name, so
# the set follows the file's own vocabulary instead of a hand-kept list.
_CREDENTIAL_NAME = re.compile(r"(PASSWORD|SECRET|TOKEN|API_KEY|_KEY|CREDENTIAL)", re.IGNORECASE)

# A shell expansion, after compose's ``$$`` escape has been undone: ``$VAR`` or
# ``${VAR}``. ``$(`` is command substitution and is deliberately not matched.
_SHELL_VARIABLE = re.compile(
    r"(?<!\$)\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|(?P<bare>[A-Za-z_][A-Za-z0-9_]*))"
)

# An environment read written the way the Python probes write it.
_PYTHON_ENVIRONMENT = re.compile(r"""os\.environ(?:\.get\(\s*|\[\s*)['"]([A-Za-z_][A-Za-z0-9_]*)['"]""")

# A shell-local variable the probe introduces itself (``code=$(curl ...)``),
# which must not be mistaken for a variable the service has to supply.
_SHELL_ASSIGNMENT = re.compile(r"(?:^|[\s;&|(])([A-Za-z_][A-Za-z0-9_]*)=")

_URL = re.compile(r"https?://[^\s'\"`|;&)]+")

_DEFAULT_PORTS = {"http": 80, "https": 443}


# --- the rendered model ------------------------------------------------------


@pytest.fixture(scope="module")
def services(tmp_path_factory) -> dict:
    cli = compose_cli()
    if cli is None:
        pytest.skip("the docker compose CLI is needed to render docker-compose.yml")
    return render_services(tmp_path_factory.mktemp("compose-render"), cli)


# --- reading the model ------------------------------------------------------


def _variable_name(match: re.Match) -> str:
    return match.group("braced") or match.group("bare")


def _environment_references(argv: tuple[str, ...]) -> set[str]:
    """Variables the probe reads from the environment when it runs.

    Shell-local variables the probe assigns itself are excluded: they come from
    the probe, not from the service.
    """
    text = "\n".join(argv)
    assigned = set(_SHELL_ASSIGNMENT.findall(text))
    return {
        _variable_name(match)
        for match in _SHELL_VARIABLE.finditer(text)
        if _variable_name(match) not in assigned
    } | set(_PYTHON_ENVIRONMENT.findall(text))


def _expand(argv: tuple[str, ...], environment: dict[str, str]) -> tuple[str, ...]:
    """Expand ``$VAR``/``${VAR}`` in argv the way the container's shell would."""

    def substitute(match: re.Match) -> str:
        return environment.get(_variable_name(match), match.group(0))

    return tuple(_SHELL_VARIABLE.sub(substitute, element) for element in argv)


def _flag_value(argv: tuple[str, ...], flag: str) -> str:
    """The value that follows ``flag`` — the password after ``--requirepass``."""
    assert flag in argv, f"{flag} is not in the argv under test: {argv}"
    index = argv.index(flag)
    assert index + 1 < len(argv), f"{flag} is the last argv element and carries no value"
    return argv[index + 1]

def _command_tokens(service: dict) -> tuple[str, ...]:
    """The command's argv, tokenised the way the container's shell reads it.

    A `sh -c` command arrives as one argv element holding the whole script, so
    it is split here; every other element is already a token.
    """
    argv = effective_argv(service, "command")
    if len(argv) >= 3 and Path(argv[0]).name == "sh" and argv[1] == "-c":
        return tuple(shlex.split(argv[2]))
    return argv


@dataclass(frozen=True)
class Endpoint:
    service: str
    scheme: str
    host: str | None
    port: int


def _probe_endpoints(name: str, service: dict) -> tuple[Endpoint, ...]:
    """Every HTTP endpoint the service's healthcheck reaches."""
    endpoints = []
    for element in effective_argv(service, "healthcheck"):
        for raw in _URL.findall(element):
            parts = urlsplit(raw)
            endpoints.append(
                Endpoint(
                    service=name,
                    scheme=parts.scheme,
                    host=parts.hostname,
                    port=parts.port or _DEFAULT_PORTS[parts.scheme],
                )
            )
    return tuple(endpoints)


def _probed_endpoints(services: dict) -> dict[str, tuple[Endpoint, ...]]:
    """The probed endpoints of every service that healthchecks over HTTP."""
    return {
        name: endpoints
        for name, service in sorted(services.items())
        if (endpoints := _probe_endpoints(name, service))
    }


def _served_container_ports(service: dict) -> frozenset[int]:
    """Ports the container itself serves — what ``expose``/``ports`` declare."""
    ports = {int(str(entry).split("/")[0]) for entry in service.get("expose") or ()}
    for entry in service.get("ports") or ():
        target = entry["target"] if isinstance(entry, dict) else str(entry).rsplit(":", 1)[-1]
        ports.add(int(target))
    return frozenset(ports)


# --- running a service's own broker resolution -------------------------------

# `rq worker` with no `--url` resolves its broker through this function against
# the process environment, and `rqscheduler` resolves its own default the same
# way. Driving the libraries instead of reimplementing their lookup is the whole
# point: a worker whose REDIS_URL disappears from its environment resolves to
# localhost, and only the library knows that.
_BROKER_RESOLUTION = """
import json, os
from rq.cli.helpers import get_redis_from_config

connection = get_redis_from_config(dict(os.environ))
kwargs = connection.connection_pool.connection_kwargs
print(json.dumps({key: kwargs.get(key) for key in ("host", "port", "db", "password")}))
"""

# rqscheduler builds its parser inside main() and then runs its loop, so the
# scheduler is stubbed at the one point that matters: the connection it was
# handed. Everything above that — argument defaults, environment lookup, the
# url/host branch — is the library's own code.
_SCHEDULER_BROKER_RESOLUTION = """
import json, sys
from rq_scheduler.scripts import rqscheduler

captured = {}


class _RecordingScheduler:
    def __init__(self, connection=None, **kwargs):
        captured["kwargs"] = connection.connection_pool.connection_kwargs

    def run(self, burst=False):
        return None


rqscheduler.Scheduler = _RecordingScheduler
rqscheduler.setup_loghandlers = lambda *args, **kwargs: None
sys.argv = ["rqscheduler"]
rqscheduler.main()
kwargs = captured["kwargs"]
print(json.dumps({key: kwargs.get(key) for key in ("host", "port", "db", "password")}))
"""


def _resolved_broker(script: str, name: str, service: dict) -> dict:
    """Run ``script`` with exactly the environment the container would have."""
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "VIRTUAL_ENV": os.environ.get("VIRTUAL_ENV", ""),
    }
    environment.update(container_environment(service))
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"{name} could not resolve a broker with the environment it is given: "
        f"{completed.stderr.strip()}"
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _assert_reaches_the_broker(name: str, resolved: dict) -> None:
    assert (resolved["host"], resolved["port"], resolved["db"]) == (
        BROKER_SERVICE,
        BROKER_PORT,
        BROKER_DB,
    ), (
        f"{name} connects to {resolved['host']}:{resolved['port']}/{resolved['db']} instead of "
        f"the {BROKER_SERVICE} service — every job it enqueues or claims goes to a redis "
        "that is not in the stack"
    )
    assert resolved["password"] == SYNTHETIC_PASSWORD, (
        f"{name} reaches {BROKER_SERVICE} without the broker password, so it is rejected on "
        "AUTH and the service never registers"
    )


# --- SEC-11: the credential must not be in a process list -------------------


def _credential_values(environment: dict[str, str]) -> set[str]:
    """Values that must never appear in a process list.

    A variable named like a credential holds one, and so does any value that
    embeds one — a connection URL with the password in it is the same secret
    with a hostname attached, which is exactly what the `--url` flags this
    stack removed used to interpolate. The set is closed over that relation
    (a fixed point over a finite set of values) so a secret that reaches argv
    inside a longer string is still caught.
    """
    seeds = {value for name, value in environment.items() if value and _CREDENTIAL_NAME.search(name)}
    carriers = set(seeds)
    growing = True
    while growing:
        growing = False
        for value in environment.values():
            if value and value not in carriers and any(seed in value for seed in seeds):
                carriers.add(value)
                growing = True
    return carriers


def test_no_container_argv_element_is_a_credential_value(services) -> None:
    """Compose's rendered argv is the container config `docker inspect` prints.

    An element equal to a credential the service was handed is the SEC-11 leak,
    in any service: the four rq/rqscheduler commands that interpolated the
    broker URL, and the redis healthcheck that handed the password to
    `redis-cli -a`.
    """
    credential_values = 0

    for name, service in sorted(services.items()):
        environment = container_environment(service)
        carriers = _credential_values(environment)
        for section in ("command", "healthcheck"):
            for element in effective_argv(service, section):
                assert element not in carriers, (
                    f"{name}: its {section} carries "
                    f"{', '.join(sorted(v for v, value in environment.items() if value == element))}"
                    " in argv — `docker inspect` and `ps` hand it to anyone who can read the "
                    "container"
                )
        credential_values += len(carriers)
    assert credential_values, (
        "no credential-valued variable was found in the rendered model, so this check would "
        "pass no matter what the argv contained"
    )


# --- SEC-11: the broker URL is the one the binaries actually read -----------


@pytest.mark.parametrize(
    "service_name", ("worker-ingest", "worker-followup", "worker-maintenance")
)
def test_worker_reaches_the_broker_through_rqs_own_resolution(
    services, service_name: str
) -> None:
    """`rq worker` resolves its broker from the environment when `--url` is absent.

    That fallback is what took the password out of argv, and it is also what
    makes the URL's absence silent: with no broker URL in the environment, rq
    builds a localhost connection and the worker registers itself with a redis
    that is not in the stack.
    """
    _assert_reaches_the_broker(
        service_name, _resolved_broker(_BROKER_RESOLUTION, service_name, services[service_name])
    )


def test_scheduler_reaches_the_broker_through_rqschedulers_own_resolution(services) -> None:
    """rqscheduler does not read `REDIS_URL`; its `--url` defaults from `RQ_REDIS_URL`.

    Dropping `--url` without exporting the URL under the name rqscheduler reads
    leaves it on its host/port defaults, so every scheduled tick is enqueued into
    a redis that is not in the stack and nothing is ever reconciled.
    """
    name = "scheduler"
    _assert_reaches_the_broker(
        name, _resolved_broker(_SCHEDULER_BROKER_RESOLUTION, name, services[name])
    )


def test_the_redis_probe_presents_the_password_the_server_was_started_with(services) -> None:
    """The healthcheck's client must present the secret the server was given.

    The server is started through a shell that expands its password, and the
    probe authenticates from the environment rather than from argv. Those two
    have to be the same secret: hand the client a stale or differently-sourced
    password and every probe fails, which parks the whole stack in
    `depends_on: service_healthy` waiting for a redis that is already up.
    """
    name = "redis"
    service = services[name]
    environment = container_environment(service)

    assert REDIS_CLIENT_AUTH_ENV in environment, (
        f"redis-cli authenticates from {REDIS_CLIENT_AUTH_ENV} once the password leaves its "
        "argv; without it the probe runs unauthenticated against a password-protected server"
    )
    server_password = _flag_value(
        _expand(_command_tokens(service), environment), "--requirepass"
    )
    assert server_password == environment[REDIS_CLIENT_AUTH_ENV], (
        f"the {name} service starts with one password and its healthcheck presents another — "
        "the probe cannot authenticate against its own server"
    )
    started_with = _flag_value(_command_tokens(service), "--requirepass")
    assert _SHELL_VARIABLE.search(started_with), (
        f"the server is started with {started_with!r} literally in argv; it has to be a "
        "$REDIS_PASSWORD reference the shell expands, or docker inspect carries the secret"
    )


# --- OPS-24: a probe that would actually go red -----------------------------


def test_every_healthcheck_declares_the_timing_keys_docker_requires(services) -> None:
    """Docker ignores an interval/timeout/retries that is absent, not invalid.

    A typo in a new probe falls back to Docker's 30s default silently, so the
    probe stops fitting the deploy window it was written for.
    """
    missing = {
        name: sorted({"interval", "timeout", "retries"} - set(service["healthcheck"]))
        for name, service in sorted(services.items())
        if service.get("healthcheck")
        and not {"interval", "timeout", "retries"} <= set(service["healthcheck"])
    }

    assert not missing, f"healthcheck(s) missing required timing keys: {missing}"


def test_every_probed_endpoint_is_a_port_its_own_service_serves(services) -> None:
    """A probe pointed at a port the service never binds can never report anything.

    nginx and the web colours serve the ports they expose, the edge the ports it
    publishes. A healthcheck naming any other port gets connection refused on
    every interval, so compose holds every dependent service in waiting forever
    while the service it is probing is serving perfectly.
    """
    audited = {
        name: (endpoints, _served_container_ports(services[name]))
        for name, endpoints in _probed_endpoints(services).items()
    }
    assert set(AUDITED_HTTP_SERVICES) <= set(audited), (
        f"the probe audit covers {sorted(AUDITED_HTTP_SERVICES)} but only these services carry "
        f"an http(s) probe in the rendered model: {sorted(audited)}"
    )

    for name, (endpoints, served) in audited.items():
        for endpoint in endpoints:
            assert endpoint.port in served, (
                f"{name} probes {endpoint.host}:{endpoint.port} but serves {sorted(served)} — "
                "the probe can never succeed, so compose never starts what depends on it"
            )


def test_every_probed_endpoint_stays_on_the_container(services) -> None:
    """The edge probes must not depend on public DNS or egress from inside.

    `wget --spider` follows a redirect, so a probe that leaves the container
    resolves the site's public name and needs working egress. A droplet behind a
    flaky resolver then flaps a healthy edge to unhealthy, and a probe aimed at
    some other host reports on something other than the container it is judging.
    """
    for name, endpoints in _probed_endpoints(services).items():
        for endpoint in endpoints:
            assert endpoint.host in {"127.0.0.1", "localhost", "::1"}, (
                f"{name} probes {endpoint.host}, which is off the container: the probe's answer "
                "would depend on public DNS and egress instead of this service's own listener"
            )


def test_the_probed_http_services_are_the_ones_under_audit(services) -> None:
    """Keeps the scope of the two probe audits above from going stale.

    A new service with an HTTP healthcheck has to be audited against its own
    served ports and host, so adding one without extending `AUDITED_HTTP_SERVICES`
    fails here instead of shipping unprobed.
    """
    probed = set(_probed_endpoints(services))

    assert probed == set(AUDITED_HTTP_SERVICES), (
        f"services carrying an http(s) healthcheck: {sorted(probed)}; "
        f"AUDITED_HTTP_SERVICES: {sorted(AUDITED_HTTP_SERVICES)}"
    )


def test_no_healthcheck_reads_a_variable_its_service_is_not_given(services) -> None:
    """A probe that reads a missing variable fails on every interval.

    The worker probes authenticate with `os.environ['REDIS_URL']`, which exists
    only because of the service's `env_file`. Lose the env_file and the probe
    raises KeyError: the container is reported unhealthy forever while the
    service itself is fine, and `depends_on: service_healthy` never opens.
    """
    references: dict[str, set[str]] = {}

    for name, service in sorted(services.items()):
        if not service.get("healthcheck"):
            continue
        environment = container_environment(service)
        for variable in _environment_references(effective_argv(service, "healthcheck")):
            references.setdefault(name, set()).add(variable)
            assert variable in environment, (
                f"{name}'s healthcheck reads ${variable}, which compose never puts in the "
                "container's environment — the probe raises on every interval and the service "
                "is reported unhealthy while it is running fine"
            )

    assert "REDIS_URL" in references.get("worker-ingest", set()), (
        "the worker healthcheck no longer reads REDIS_URL, so this check has stopped covering "
        f"the probes that depend on it (references found: {references})"
    )
