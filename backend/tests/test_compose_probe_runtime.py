"""Do the compose healthchecks actually go red when the service is broken?

``test_compose_service_contracts.py`` proves each probe names a real endpoint on
the service that owns it. That is necessary and not sufficient: a probe can
address the right port and still exit 0 no matter what it finds, which is how an
edge stays ``healthy`` while it serves 502s — the failure OPS-24 was filed for.
These tests run the rendered probes, in the rendered image, against listeners
whose answer is chosen by the test, and assert the exit code follows it.

Nothing here asserts on configuration text. The probe argv, the image, the
environment and the server command all come from ``docker compose config``;
what is asserted is the exit code and the output of a process that ran.

Scope, and the two places it stops short:

* the edge probes are executed in the image the *caddy* service declares, which
  is the busybox-wget + curl alpine the frontend's nginx-alpine base matches.
  What is under test is the probe command's behaviour, not that image's
  contents; that the frontend image really ships ``wget`` is a separate image
  check that only runs when the pushed image is available locally.
* the edge listener is a stub, not a TLS-terminating Caddy with the site's
  Caddyfile. It answers the status codes the real edge answers under auto-TLS
  (200 and 308) and the one it must never accept (502), which is the whole
  contract the probe has.

Every container here is started and torn down by the test itself, on the local
docker socket; nothing outside this machine is contacted.

Skipped when docker is unavailable or the pinned image is not present locally —
never silently passed.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator

import pytest

from tests.helpers.compose_model import (
    REDIS_CLIENT_AUTH_ENV,
    compose_cli,
    container_environment,
    effective_argv,
    render_services,
)

_READY_TIMEOUT_SECONDS = 15
_REDIRECT_TARGET = "http://edge.invalid/probe-followed"  # RFC 6761: never resolves


def _docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=False)


def _image_available(reference: str) -> bool:
    return _docker("image", "inspect", reference).returncode == 0


@pytest.fixture(scope="module")
def services(tmp_path_factory) -> dict:
    cli = compose_cli()
    if cli is None:
        pytest.skip("the docker compose CLI is needed to render docker-compose.yml")
    return render_services(tmp_path_factory.mktemp("compose-probe-render"), cli)


def _require_image(reference: str) -> str:
    if not _image_available(reference):
        pytest.skip(f"{reference} is not available locally, so the probe cannot be executed")
    return reference


def _exec(container: str, argv: tuple[str, ...], **environment: str) -> subprocess.CompletedProcess:
    """Run argv inside a running container the way compose would run the probe.

    ``argv`` already carries compose's ``$$`` escapes resolved and, for a shell
    form, the ``/bin/sh -c`` the daemon would prepend.
    """
    return _docker(
        "exec",
        *(f"--env={key}={value}" for key, value in environment.items()),
        container,
        *argv,
    )


def _wait_until_serving(container: str, port: int = 80) -> None:
    """Block until the container's loopback listener answers, whatever it answers."""
    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        probe = _exec(container, ("curl", "-s", "-o", "/dev/null", f"http://127.0.0.1:{port}/"))
        if probe.returncode == 0:
            return
        time.sleep(0.25)
    raise AssertionError(f"the stub listener never started answering on 127.0.0.1:{port}")


@pytest.fixture
def stub_listener(services) -> Iterator:
    """Run a container that answers a chosen status on :80, and yield its id."""
    image = _require_image(services["caddy"]["image"])
    started: list[str] = []

    def start(*respond_args: str) -> str:
        container = _docker(
            "run", "-d", "--rm", image, "caddy", "respond", "--listen", ":80", *respond_args
        )
        assert container.returncode == 0, container.stderr
        container_id = container.stdout.strip()
        started.append(container_id)
        _wait_until_serving(container_id)
        return container_id

    try:
        yield start
    finally:
        for container_id in started:
            _docker("rm", "-f", container_id)


# --- redis: the probe against the server it was rendered for -----------------


@pytest.fixture(scope="module")
def redis_container(services) -> Iterator[str]:
    """The rendered redis service, running, with its rendered environment."""
    service = services["redis"]
    _require_image(service["image"])
    run = _docker(
        "run",
        "-d",
        "--rm",
        *(f"--env={key}={value}" for key, value in container_environment(service).items()),
        service["image"],
        *effective_argv(service, "command"),
    )
    assert run.returncode == 0, run.stderr
    container = run.stdout.strip()
    try:
        deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if _exec(container, ("redis-cli", "ping")).returncode == 0:
                break
            time.sleep(0.25)
        else:
            raise AssertionError("the rendered redis service never came up")
        yield container
    finally:
        _docker("rm", "-f", container)


def test_the_redis_probe_answers_pong_against_the_rendered_server(
    services, redis_container: str
) -> None:
    """The healthcheck's own argv, run as the daemon runs it, gets PONG.

    Anything that reports a redis that is not answering — a probe whose client
    was renamed, an argv that compose hands over differently than the file reads
    — fails here instead of on the droplet, where it parks every dependent
    service in waiting.
    """
    probe = _exec(redis_container, effective_argv(services["redis"], "healthcheck"))

    assert probe.returncode == 0, f"the rendered probe failed: {probe.stderr or probe.stdout}"
    assert probe.stdout.strip() == "PONG", (
        f"the rendered probe answered {probe.stdout.strip()!r}, not PONG: something in the "
        "service's environment is not reaching the client"
    )


def test_the_redis_probe_only_answers_pong_with_the_password_the_server_was_given(
    services, redis_container: str
) -> None:
    """The probe's credential is the server's credential, and that is checkable.

    `redis-cli` answers NOAUTH and still exits 0, so a PONG is the only thing
    that distinguishes "the probe authenticated" from "a redis answered". With
    the service's own environment the client gets PONG; with anything else the
    server refuses it, which is what makes the first result mean something.
    """
    probe_argv = effective_argv(services["redis"], "healthcheck")

    authenticated = _exec(redis_container, probe_argv)
    assert authenticated.stdout.strip() == "PONG", authenticated.stdout

    rejected = _exec(redis_container, probe_argv, **{REDIS_CLIENT_AUTH_ENV: "not-the-password"})
    assert rejected.stdout.strip() != "PONG", (
        "the server accepted a probe carrying the wrong password, so the PONG above proves "
        "nothing about the credential the service hands its own probe"
    )


def test_the_redis_probe_goes_red_when_the_server_is_not_answering(services) -> None:
    """A probe that cannot fail is not a probe.

    The same argv, run in the same image with the server replaced by a process
    that never listens, has to exit non-zero — otherwise the redis service is
    reported healthy while every worker fails to reach the broker.
    """
    service = services["redis"]
    _require_image(service["image"])
    run = _docker("run", "-d", "--rm", service["image"], "sleep", "600")
    assert run.returncode == 0, run.stderr
    container = run.stdout.strip()
    try:
        probe = _exec(
            container,
            effective_argv(service, "healthcheck"),
            **{key: value for key, value in container_environment(service).items()},
        )
        assert probe.returncode != 0, (
            f"the probe exited 0 against a container serving nothing: {probe.stdout!r}"
        )
    finally:
        _docker("rm", "-f", container)


# --- the edge: the probe against the answers the edge really gives -----------


@pytest.mark.parametrize("status", (200, 308))
def test_the_edge_probe_reports_healthy_on_the_answers_the_edge_gives(
    services, stub_listener, status: int
) -> None:
    """With auto-TLS the edge answers :80 with 200 or 308; both are healthy.

    Treating the 308 as a failure marks a working edge unhealthy and, with
    `depends_on` chains behind it, can stop a deploy mid-cutover.
    """
    container = stub_listener("--status", str(status))
    probe = _exec(container, effective_argv(services["caddy"], "healthcheck"))

    assert probe.returncode == 0, (
        f"the rendered edge probe called a healthy {status} a failure: "
        f"{probe.stdout.strip() or probe.stderr.strip()}"
    )


def test_the_edge_probe_reports_unhealthy_on_an_error_status(services, stub_listener) -> None:
    """The half of the contract that makes the other half mean anything.

    A Caddy that failed to load its Caddyfile answers 502 on every request; the
    probe has to notice, or the edge keeps reporting `up` to compose while
    serving nothing.
    """
    container = stub_listener("--status", "502")
    probe = _exec(container, effective_argv(services["caddy"], "healthcheck"))

    assert probe.returncode != 0, (
        f"the rendered edge probe called a 502 healthy: {probe.stdout.strip()!r}"
    )


def test_the_edge_probe_does_not_follow_the_redirect_off_the_container(
    services, stub_listener
) -> None:
    """A probe that leaves the container reports on something else.

    The 308 the real edge sends points at the site's public name. A probe that
    followed it would resolve that name and leave the container, so a resolver or
    egress blip on the droplet would flap a healthy edge to unhealthy. The
    redirect target here is a name that cannot resolve, so a probe that follows
    it cannot answer at all.
    """
    container = stub_listener(
        "--status", "308", "--header", f"Location: {_REDIRECT_TARGET}"
    )
    probe = _exec(container, effective_argv(services["caddy"], "healthcheck"))

    assert probe.returncode == 0, (
        f"the edge probe left the container: it followed the 308 to {_REDIRECT_TARGET} instead "
        f"of reporting on its own listener ({probe.stdout.strip() or probe.stderr.strip()})"
    )


def test_the_frontend_probe_is_green_only_while_its_port_is_being_served(
    services, stub_listener
) -> None:
    """nginx serves the SPA on :80, so that is the only port a probe can use.

    The listener answering on :80 is the frontend serving; the same probe against
    a container listening elsewhere is a frontend that is not. This is the check
    that catches a healthcheck pointed at a port the service never binds — the
    failure mode that leaves a broken frontend looking `running`.
    """
    probe_argv = effective_argv(services["frontend"], "healthcheck")

    serving = stub_listener("--status", "200")
    assert _exec(serving, probe_argv).returncode == 0, (
        "the frontend probe failed against a listener serving :80, the port the service exposes"
    )

    elsewhere = services["caddy"]["image"]
    run = _docker(
        "run", "-d", "--rm", elsewhere, "caddy", "respond", "--listen", ":8081", "--status", "200"
    )
    assert run.returncode == 0, run.stderr
    container = run.stdout.strip()
    try:
        _wait_until_serving(container, 8081)
        probe = _exec(container, probe_argv)
        assert probe.returncode != 0, (
            f"the frontend probe exited 0 against a container serving only :8081: "
            f"{probe.stdout.strip()!r}"
        )
    finally:
        _docker("rm", "-f", container)


def test_an_exec_form_probe_names_a_binary_its_image_ships(services) -> None:
    """A probe naming a binary the image does not ship can never pass.

    The healthcheck is the only signal compose has that these services came up,
    so a probe whose client the image lacks marks a perfectly healthy container
    `unhealthy` forever. Only the exec form names a binary directly; a shell
    probe names its clients inside a script, and those are proved instead by
    running the probe in the image, which the tests above do.
    """
    exec_probes = {
        name: service
        for name, service in sorted(services.items())
        if ((service.get("healthcheck") or {}).get("test") or [None])[0] == "CMD"
    }
    assert exec_probes, (
        "no service uses the exec healthcheck form, so this check would pass without "
        "looking at anything"
    )

    checked = 0
    for name, service in exec_probes.items():
        if not _image_available(service["image"]):
            continue
        client = effective_argv(service, "healthcheck")[0]
        resolved = _docker(
            "run", "--rm", "--entrypoint", "/bin/sh", service["image"], "-c",
            f"command -v {client}",
        )
        assert resolved.returncode == 0, (
            f"{name}'s healthcheck runs {client!r}, which {service['image']} does not resolve: "
            f"{resolved.stderr.strip()}"
        )
        checked += 1

    if not checked:
        pytest.skip(
            f"none of the exec-probe images "
            f"{[service['image'] for service in exec_probes.values()]} are available locally"
        )
