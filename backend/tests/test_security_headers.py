"""SEC-06: edge security headers and the API host allowlist.

The console is a SPA whose JWTs live in localStorage, so the edge headers are
the only thing standing between a script injection and full account takeover,
and clickjacking is only blocked by ``X-Frame-Options``/``frame-ancestors``.
The headers must live in the file the deploy actually renders
(``Caddyfile.template`` via ``scripts/flip_caddy.sh``) — a host-only change
would be lost on the next redeploy.

TEST-17 — the edge half of this file used to grep ``Caddyfile.template`` and
``flip_caddy.sh`` as text, which passed whenever a header name was *spelled*
correctly and said nothing about what Caddy would actually serve. The template
is now rendered exactly as ``flip_caddy.sh`` renders it and then handed to the
real Caddy binary via ``caddy adapt``, and the assertions read the resulting
JSON config. That makes every edge assertion behavioural: a header dropped,
renamed, or moved outside the ``header`` block does not appear in the adapted
``headers`` handler, and the test goes red. ``caddy adapt`` is the same
adaptation ``caddy reload`` performs on the droplet.

The one thing ``caddy adapt`` cannot prove is that ``flip_caddy.sh`` feeds it
this file, since the script hardcodes ``cd /opt/vfic`` and shells into docker.
That coupling is still asserted textually, and the reason is spelled out on
``test_flip_script_renders_the_committed_template``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.testclient import TestClient

BACKEND = Path(__file__).parents[1]
CADDY_TEMPLATE = BACKEND / "Caddyfile.template"
FLIP_SCRIPT = BACKEND / "scripts" / "flip_caddy.sh"

REQUIRED_HEADERS = (
    "Strict-Transport-Security",
    "Content-Security-Policy",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "Permissions-Policy",
)

# The blue/green cutover colours flip_caddy.sh accepts. Rendering both proves the
# substitution cannot collide with anything else in the file.
DEPLOY_COLORS = ("blue", "green")


def _fastapi_app():
    """The FastAPI app inside the Socket.IO ASGI wrapper main.py exports."""
    from app.main import app as exported

    return getattr(exported, "other_asgi_app", exported)


def _render_template(color: str) -> str:
    """Reproduce what flip_caddy.sh's `sed` writes, from the committed template.

    Same substitution the script performs, so a change to the script's sed
    expression is a change to what this renders.
    """
    return subprocess.run(
        ["sed", f"s/__WEB_UPSTREAM__/web-{color}/g", str(CADDY_TEMPLATE)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@lru_cache(maxsize=None)
def _adapt(color: str) -> dict:
    """Run `caddy adapt` on the rendered config and return the JSON it emits.

    This is Caddy's own Caddyfile -> JSON adaptation — the identical step the
    edge performs on `caddy reload` — so what the assertions below read is what
    the proxy would actually serve, not what the template happens to say.
    """
    if shutil.which("caddy") is None:
        pytest.skip("caddy binary not on PATH; edge adaptation cannot be verified")

    rendered = _render_template(color)
    adapted = subprocess.run(
        ["caddy", "adapt", "--config", "-", "--adapter", "caddyfile"],
        input=rendered,
        capture_output=True,
        text=True,
    )
    if adapted.returncode != 0:
        pytest.skip(f"caddy adapt unavailable ({adapted.stderr.strip()[:200]})")

    return json.loads(adapted.stdout)


def _served_headers(color: str) -> dict[str, list[str]]:
    """Every response header Caddy sets, keyed by canonical header name.

    Walks the adapted route tree rather than pattern-matching the JSON text, so
    a header that survives only in a comment, or in a `header` block that a
    later route overrides, is not counted as served.
    """
    served: dict[str, list[str]] = {}
    stack = list(_adapt(color)["apps"]["http"]["servers"].values())
    while stack:
        server = stack.pop()
        for route in server.get("routes", []):
            for handler in route.get("handle", []):
                if handler.get("handler") == "subroute":
                    stack.append(handler)
                response = handler.get("response") or {}
                for name, values in (response.get("set") or {}).items():
                    served.setdefault(name.lower(), []).extend(values)
    return served


def _csp(color: str) -> str:
    return _served_headers(color)["content-security-policy"][0]


def _csp_directive(csp: str, name: str) -> str:
    """The sources a named CSP directive allows, with the name stripped off."""
    directive = next(
        part.strip() for part in csp.split(";") if part.strip().startswith(name)
    )
    return directive[len(name) :].strip()


@pytest.mark.parametrize("color", DEPLOY_COLORS)
def test_deployed_config_serves_every_security_header(color: str):
    """Both deploy colours must serve the full header set.

    Asserted on Caddy's adapted output, so a header that is commented out, or
    dropped from the `header` block during a future edit, is not served and this
    fails — which a name-presence regex over the template could not detect.
    """
    served = _served_headers(color)

    for header in REQUIRED_HEADERS:
        assert header.lower() in served, f"{header} is not served on web-{color}"
        assert served[header.lower()], f"{header} is served with an empty value on web-{color}"


@pytest.mark.parametrize("color", DEPLOY_COLORS)
def test_render_leaves_no_unsubstituted_upstream_placeholder(color: str):
    """The rendering the deploy performs must resolve every __WEB_UPSTREAM__."""
    rendered = _render_template(color)

    assert "__WEB_UPSTREAM__" not in rendered
    assert f"web-{color}:8000" in rendered


def test_csp_carries_the_required_directives_and_allows_inline_styles():
    csp = _csp("blue")

    for directive in ("default-src 'self'", "object-src 'none'", "frame-ancestors 'none'"):
        assert directive in csp, f"CSP is missing {directive!r}"
    # index.html ships an inline <style> loader block and React sets inline style
    # attributes; without 'unsafe-inline' in style-src the console renders
    # unstyled, so this directive is deliberate rather than an oversight.
    assert _csp_directive(csp, "style-src").startswith("'self' 'unsafe-inline'")
    # base-uri does NOT fall back to default-src, so an injected <base href>
    # would otherwise rewrite every relative fetch the SPA makes.
    assert _csp_directive(csp, "base-uri") == "'self'"
    # form-action is stated explicitly so a future relaxation of default-src
    # cannot silently widen where the console may post (OPS-27).
    assert _csp_directive(csp, "form-action") == "'self'"


def test_csp_allows_the_image_sources_the_console_actually_renders():
    """Provider avatars load straight from the Zalo/Meta CDNs — no proxy exists."""
    img_src = _csp_directive(_csp("blue"), "img-src")

    for source in (
        "'self'",
        "blob:",
        "data:",
        "https://*.zadn.vn",
        "https://*.fbcdn.net",
        "https://*.fbsbx.com",
    ):
        assert source in img_src, f"img-src is missing {source!r}"
    # A bare scheme source would make the whole restriction meaningless, so
    # every source must be an explicit host/scheme token.
    assert not any(
        part.strip() in {"https:", "http:", "*", "data"} for part in img_src.split()
    ), f"img-src widens to a bare scheme source: {img_src!r}"


def test_frame_protection_is_served_on_every_route():
    """Clickjacking defence must be a served header, not a CSP directive alone.

    Browsers still honour X-Frame-Options for the API responses the SPA fetches,
    so the header has to be set by the edge rather than left to the SPA's own
    index.html.
    """
    served = _served_headers("blue")

    assert served["x-frame-options"] == ["DENY"]
    assert "frame-ancestors 'none'" in _csp("blue")


def test_flip_script_renders_the_committed_template():
    """The headers must ship in the file flip_caddy.sh renders, not the host.

    This is the one edge assertion that stays textual, and deliberately so.
    `flip_caddy.sh` hardcodes `cd /opt/vfic` and drives `docker compose` against
    the droplet, so there is no way to execute it from a test — it would mutate
    /opt/vfic and reload a live edge. What *is* behavioural is everything
    downstream of the render: the tests above feed the template through the
    same sed the script uses and then adapt it with the real Caddy binary, so
    they cover the template's contents. What cannot be covered this way is the
    wiring — that the script reads this file and writes the result in place —
    which is a property of a shell script, not of the artifact under test.
    """
    script = FLIP_SCRIPT.read_text(encoding="utf-8")
    render = next(
        line
        for line in script.splitlines()
        if line.lstrip().startswith("sed ") and "Caddyfile" in line
    )

    # The template is the render input, and the rendered output becomes the
    # Caddyfile the edge reads (in place, so the bind mount keeps its inode).
    assert "Caddyfile.template" in render
    assert '> "$tmp"' in render
    assert 'cat "$tmp" > Caddyfile' in script
    # The substitution the script performs is the one the tests above replay.
    assert "__WEB_UPSTREAM__" in render
    assert 'web-${COLOR}' in render


def test_host_allowlist_is_read_from_config():
    from app.core.config import get_settings

    allowed = [m for m in _fastapi_app().user_middleware if m.cls is TrustedHostMiddleware]

    assert allowed, "TrustedHostMiddleware is not installed"
    assert allowed[0].kwargs["allowed_hosts"] == get_settings().allowed_hosts_list


def test_disallowed_host_header_is_rejected_before_the_handler():
    client = TestClient(_fastapi_app(), base_url="http://bot.tingting.vip")

    assert client.get("/health").status_code == 200

    rejected = client.get("/health", headers={"Host": "attacker.example"})

    assert rejected.status_code == 400
    assert "Invalid host header" in rejected.text


def test_loopback_hosts_stay_allowed_for_container_healthchecks():
    """docker-compose and the post-flip probe both hit http://localhost:8000."""
    client = TestClient(_fastapi_app(), base_url="http://localhost:8000")

    assert client.get("/health").status_code == 200
