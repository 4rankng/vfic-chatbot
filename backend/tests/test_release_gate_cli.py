from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace

from scripts import release_gate_check as cli


def _settings(**overrides) -> SimpleNamespace:
    defaults = {
        "release_gate_correctness_enabled": True,
        "release_gate_latency_slo_enabled": True,
        "release_gate_full_answer_p95_ms": 4000,
        "release_gate_error_rate_pct": 1.0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class _ForbiddenSessionFactory:
    def __call__(self):
        raise AssertionError("async_session should not be used")


async def test_cli_skips_dependencies_when_both_gates_disabled(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: _settings(
            release_gate_correctness_enabled=False,
            release_gate_latency_slo_enabled=False,
        ),
    )
    monkeypatch.setattr(
        cli,
        "_load_golden_pass_rate",
        lambda path: (_ for _ in ()).throw(AssertionError("golden results should not load")),
    )
    monkeypatch.setattr(cli, "async_session", _ForbiddenSessionFactory())

    rc = await cli._run(Namespace(golden_results=tmp_path / "missing.json", window_hours=24))

    captured = capsys.readouterr()
    assert rc == 0
    assert "not evaluated:" in captured.out
    assert "correctness: disabled by settings" in captured.out
    assert "latency_slo: disabled by settings" in captured.out


async def test_cli_blocks_on_missing_golden_file_when_correctness_enabled(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: _settings(release_gate_latency_slo_enabled=False),
    )
    monkeypatch.setattr(cli, "async_session", _ForbiddenSessionFactory())

    rc = await cli._run(Namespace(golden_results=tmp_path / "missing.json", window_hours=24))

    captured = capsys.readouterr()
    assert rc == 1
    assert "golden results file not found" in captured.err


async def test_cli_blocks_on_malformed_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: _settings(release_gate_latency_slo_enabled=False),
    )
    monkeypatch.setattr(cli, "async_session", _ForbiddenSessionFactory())
    malformed = tmp_path / "gold.json"
    malformed.write_text("{", encoding="utf-8")

    rc = await cli._run(Namespace(golden_results=malformed, window_hours=24))

    captured = capsys.readouterr()
    assert rc == 1
    assert "golden results JSON is invalid" in captured.err


def test_cli_blocks_on_invalid_window(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: _settings(
            release_gate_correctness_enabled=False,
            release_gate_latency_slo_enabled=False,
        ),
    )

    rc = cli.main(["--window-hours", "0"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "window_hours must be greater than zero" in captured.err


def test_cli_help():
    parser = cli._build_parser()
    help_text = parser.format_help()
    assert "--golden-results" in help_text
    assert "--window-hours" in help_text
