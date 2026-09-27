"""The backend coverage ratchet must be a floor, not report-only config.

`backend/.coveragerc` is what makes the release gate's backend lane a coverage
gate at all. pytest-cov loads it, copies `fail_under` and `precision` off the
config it read (`pytest_cov/plugin.py`, in `pytest_sessionfinish`) and enforces
them with `coverage.results.should_fail_under(total, fail_under, precision)`.
These tests drive that same path against the real config file, so the two ways
the gate can silently go green again fail here instead:

* the floor is dropped back to 0, which no total can violate;
* the floor is applied to the wrong denominator — the gate passes a bare
  `--cov` with no path, so the measured tree is whatever `source`/`omit` say.

Both are read through coverage's own parser and matcher, i.e. the same objects
`coverage.inorout.InOrOut.should_trace` consults at measurement time.
"""

from __future__ import annotations

from pathlib import Path

from coverage import Coverage
from coverage.files import GlobMatcher, prep_patterns
from coverage.results import should_fail_under

BACKEND_DIR = Path(__file__).resolve().parents[1]
COVERAGERC = BACKEND_DIR / ".coveragerc"


def _gate_coverage() -> Coverage:
    """Load the config the release gate's coverage invocation reads."""
    coverage = Coverage(config_file=str(COVERAGERC))
    coverage.load()
    return coverage


def test_configured_floor_rejects_a_below_floor_run_and_accepts_a_full_one() -> None:
    config = _gate_coverage().config
    floor = config.fail_under
    precision = config.precision

    assert 0 < floor <= 100.0, (
        f"fail_under={floor} cannot fail a run: the gate is report-only until the floor is a "
        "positive percentage the measured total can be below."
    )
    # The predicate pytest-cov applies to the measured total. A run that measured
    # nothing (tests deleted, imports broken, `--cov` pointed at an empty tree)
    # must fail the gate; a fully covered tree must pass, so the floor is not a
    # permanently-red gate either.
    assert should_fail_under(0.0, floor, precision) is True
    assert should_fail_under(100.0, floor, precision) is False


def test_floor_is_measured_over_the_app_package_only() -> None:
    config = _gate_coverage().config

    # The gate runs a bare `--cov` (no path), so `source` is the only thing
    # deciding what gets measured. Without it the floor would be compared to
    # whatever the runner happened to import, tests included.
    assert list(config.source) == ["app"]

    omit = GlobMatcher(prep_patterns(list(config.run_omit)), "omit")
    assert omit.match(str(BACKEND_DIR / "tests" / "conftest.py")) is True
    assert omit.match(str(BACKEND_DIR / "alembic" / "env.py")) is True
    assert omit.match(str(BACKEND_DIR / "app" / "core" / "config.py")) is False
