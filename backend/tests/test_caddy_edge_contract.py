"""Regression guard (20/11/2026 incident): the Caddy edge template is the
single source of truth for site routes — flip_caddy.sh re-renders /opt/vfic/
Caddyfile from it on every deploy, so a block missing here silently takes a
whole site down (that is exactly how tingtingsoft.vn died: its block was never
in the template, and a blue/green flip wiped the live route). Every host below
must have a block; add new public sites here too."""

from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "Caddyfile.template"
REQUIRED_HOSTS = (
    "bot.tingting.vip",
    "plan.tingting.vip",
    "book.tingting.vip",
    "tingtingsoft.vn",
    "www.tingtingsoft.vn",
)


def test_every_public_host_has_a_block_in_the_edge_template() -> None:
    src = TEMPLATE.read_text(encoding="utf-8")
    missing = [h for h in REQUIRED_HOSTS if f"{h} {{" not in src]
    assert not missing, f"Caddyfile.template missing site blocks: {missing}"


def test_no_blue_green_upstream_token_in_the_static_site_routes() -> None:
    """tingtingsoft.vn and book/plan are static reverse proxies — never
    __WEB_UPSTREAM__ targets, so a flip can never retarget them."""
    src = TEMPLATE.read_text(encoding="utf-8")
    for host in ("tingtingsoft.vn {", "book.tingting.vip {", "plan.tingting.vip {"):
        block = src.split(host, 1)[1].split("\n}", 1)[0]
        assert "__WEB_UPSTREAM__" not in block, f"{host} must not use __WEB_UPSTREAM__"
