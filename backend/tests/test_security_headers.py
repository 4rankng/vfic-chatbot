"""SEC-06: edge security headers and the API host allowlist.

The console is a SPA whose JWTs live in localStorage, so the edge headers are
the only thing standing between a script injection and full account takeover,
and clickjacking is only blocked by ``X-Frame-Options``/``frame-ancestors``.
The headers must live in the file the deploy actually renders
(``Caddyfile.template`` via ``scripts/flip_caddy.sh``) — a host-only change
would be lost on the next redeploy.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

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


def _fastapi_app():
    """The FastAPI app inside the Socket.IO ASGI wrapper main.py exports."""
    from app.main import app as exported

    return getattr(exported, "other_asgi_app", exported)


def _declared_header_names(caddyfile: str) -> set[str]:
    """Header names declared by the `header` block (first token of each line)."""
    return {
        line.strip().split(" ", 1)[0]
        for line in caddyfile.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def test_deploy_rendered_template_declares_every_security_header():
    template = CADDY_TEMPLATE.read_text(encoding="utf-8")
    declared = _declared_header_names(template)

    for header in REQUIRED_HEADERS:
        assert header in declared, f"{header} missing from Caddyfile.template"


def test_csp_carries_the_required_directives_and_allows_inline_styles():
    template = CADDY_TEMPLATE.read_text(encoding="utf-8")
    csp = next(
        line.strip() for line in template.splitlines() if "Content-Security-Policy" in line
    )

    for directive in ("default-src 'self'", "object-src 'none'", "frame-ancestors 'none'"):
        assert directive in csp, f"CSP is missing {directive!r}"
    # index.html ships an inline <style> loader block and React sets inline style
    # attributes; without 'unsafe-inline' in style-src the console renders
    # unstyled, so this directive is deliberate rather than an oversight.
    assert "style-src 'self' 'unsafe-inline'" in csp


def test_csp_allows_the_image_sources_the_console_actually_renders():
    """Provider avatars load straight from the Zalo/Meta CDNs — no proxy exists."""
    template = CADDY_TEMPLATE.read_text(encoding="utf-8")
    csp = next(
        line.strip() for line in template.splitlines() if "Content-Security-Policy" in line
    )
    img_src = next(part for part in csp.split(";") if part.strip().startswith("img-src"))

    for source in ("'self'", "blob:", "https://*.zadn.vn", "https://*.fbcdn.net"):
        assert source in img_src, f"img-src is missing {source!r}"
    # A bare scheme source would make the restriction meaningless.
    assert " https:;" not in csp and not csp.rstrip().endswith(" https:\"")


def test_flip_script_renders_the_committed_template():
    """The headers must ship in the file flip_caddy.sh renders, not the host."""
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


def test_rendered_caddyfile_keeps_every_security_header():
    """Rendering the template (what the deploy does) must not drop a header."""
    rendered = subprocess.run(
        ["sed", "s/__WEB_UPSTREAM__/web-blue/g", str(CADDY_TEMPLATE)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert "__WEB_UPSTREAM__" not in rendered
    declared = _declared_header_names(rendered)
    for header in REQUIRED_HEADERS:
        assert header in declared


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
