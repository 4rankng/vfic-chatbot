"""The backend coverage ratchet must be a floor, not report-only config.

``backend/.coveragerc`` is what makes the release gate's backend lane a coverage
gate at all: pytest-cov loads it, copies ``fail_under`` and ``precision`` off the
config it read (``pytest_cov/plugin.py``, in ``pytest_sessionfinish``) and
enforces them with ``coverage.results.should_fail_under``. These tests drive
that same path against the real config file, so the two ways the gate can
silently go green again fail here instead:

* the floor is lowered to a value no run can fall under, which turns the gate
  back into a report;
* the floor is applied to the wrong denominator. The gate runs a bare ``--cov``
  with no path, so the measured tree is whatever ``source``/``omit`` say — the
  gate can end up comparing the floor against the tests it just ran.

Both are exercised the way the gate experiences them, not by reading the config
as text: the floor is fed to ``should_fail_under`` at the totals a run can
actually produce, and the denominator is established by *measuring* a scratch
tree with the shipped config in a subprocess. The scratch tree is fully covered
where it matters and half covered in the app, so a config that stopped measuring
the app package would report a total the gate would happily accept.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from coverage import Coverage
from coverage.results import should_fail_under

BACKEND_DIR = Path(__file__).resolve().parents[1]
COVERAGERC = BACKEND_DIR / ".coveragerc"

# The floor `backend/.coveragerc` configures. Pinned, because a ratchet with no
# fixed number has no teeth: `0 < floor <= 100` is satisfied by 1, and a gate
# floored at 1 reports a total instead of enforcing one. Move this constant
# *with* `[report] fail_under` when the floor is raised — never lower either.
CONFIGURED_FLOOR = 75.0
CONFIGURED_PRECISION = 1


def _gate_coverage() -> Coverage:
    """Load the config the release gate's coverage invocation reads."""
    coverage = Coverage(config_file=str(COVERAGERC))
    coverage.load()
    return coverage


# --- a real measurement of the shipped config --------------------------------

# The non-app files carry far more covered statements than the app package does,
# so a config that let them into the total would push it over the floor rather
# than merely shift it.
_SCRATCH_FILES = {
    "app/covered.py": "def one():\n    return 1\n\n\ndef two():\n    return 2\n",
    "app/partly.py": "".join(f"line_{index} = {index}\n" for index in range(10)),
    "app/workers/run_worker.py": "def main():\n    return 1\n",
    "tests/test_probe.py": "".join(f"covered_{index} = {index}\n" for index in range(100)),
    "alembic/env.py": "".join(f"REVISION_{index} = 'head'\n" for index in range(10)),
}

# `app/partly.py` is executed up to this many lines, so the app package lands
# well under the floor while the rest of the tree is fully covered.
_PARTLY_EXECUTED_LINES = 4

# Measures the scratch tree with the shipped config, in a subprocess so a
# coverage session already running under `--cov` (which is how the release gate
# invokes pytest) is not disturbed by a second tracer.
_MEASUREMENT = """
import io, json, os, runpy, sys

os.chdir(sys.argv[1])
import coverage

config = coverage.Coverage(config_file=".coveragerc", data_file=None).config
fail_under, precision = config.fail_under, config.precision

cov = coverage.Coverage(config_file=".coveragerc", data_file=None)
cov.start()
for path in ("app/covered.py", "app/workers/run_worker.py", "tests/test_probe.py", "alembic/env.py"):
    runpy.run_path(path, run_name="__ratchet_probe__")
source = open("app/partly.py").read().splitlines(True)[: int(sys.argv[2])]
exec(compile("".join(source), "app/partly.py", "exec"), {"__name__": "__ratchet_probe__"})
cov.stop()

print(json.dumps({
    "fail_under": fail_under,
    "precision": precision,
    "measured": sorted(os.path.relpath(name) for name in cov.get_data().measured_files()),
    "total": cov.report(file=io.StringIO()),
}))
"""


@pytest.fixture(scope="module")
def measured(tmp_path_factory) -> dict:
    """A real coverage run of a scratch tree, using the shipped config verbatim."""
    project = tmp_path_factory.mktemp("coverage-ratchet")
    for name, body in _SCRATCH_FILES.items():
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    (project / ".coveragerc").write_text(COVERAGERC.read_text(encoding="utf-8"), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-c", _MEASUREMENT, str(project), str(_PARTLY_EXECUTED_LINES)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"the shipped .coveragerc could not measure a tree: {completed.stderr.strip()}"
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_the_gate_fails_a_run_below_the_configured_floor(measured: dict) -> None:
    """The floor is a specific percentage, and it is the one pytest-cov enforces.

    A total a point under the floor has to turn the run red, and a run exactly
    at it has to stay green — otherwise the gate is either a step backwards
    nobody can take or a wall the suite can never clear.
    """
    floor, precision = measured["fail_under"], measured["precision"]

    assert (floor, precision) == (CONFIGURED_FLOOR, CONFIGURED_PRECISION), (
        f".coveragerc configures fail_under={floor} precision={precision}; the gate's floor is "
        f"pinned at {CONFIGURED_FLOOR} (precision {CONFIGURED_PRECISION}). Raise the pin with "
        "the floor; never lower either — a floor no run can fall under is a report, not a gate."
    )
    assert should_fail_under(CONFIGURED_FLOOR - 1, floor, precision) is True, (
        f"a run measuring {CONFIGURED_FLOOR - 1}% passed a floor of {floor}%: a regression of a "
        "single point ships green"
    )
    assert should_fail_under(CONFIGURED_FLOOR, floor, precision) is False, (
        f"a run measuring exactly {floor}% failed its own floor: the gate can never go green, so "
        "it stops being read"
    )


def test_the_floor_is_measured_over_the_app_package_only(measured: dict) -> None:
    """What the floor is compared against is the app, not the tree around it.

    The gate runs a bare `--cov` with no path, so `source`/`omit` alone decide
    the denominator. Everything outside `app` is fully covered in this tree, so
    a config that let the tests, the migrations or the omitted worker module into
    the total would report them as measured here.
    """
    assert measured["measured"] == ["app/covered.py", "app/partly.py"], (
        f"the measured tree is {measured['measured']}, not the app package alone: the floor would "
        "be compared against test and migration coverage as well as application coverage"
    )


def test_a_half_covered_app_package_turns_the_gate_red(measured: dict) -> None:
    """The end-to-end claim: covered tests cannot offset uncovered application.

    This is what the two tests above add up to, measured end to end — the
    scratch tree's tests, migrations and worker module are all fully executed
    and none of them may lift the total over the floor.
    """
    total, floor, precision = measured["total"], measured["fail_under"], measured["precision"]

    assert should_fail_under(total, floor, precision) is True, (
        f"the measured total is {total}% against a {floor}% floor and the gate still passed: "
        "something outside app/ is being counted, or the floor is not enforced"
    )
