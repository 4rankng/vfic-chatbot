"""Both Page-scope bind parameters must be supplied on every path.

The scoped-catalog predicate added two placeholders to the match SQL, but they
were only bound when a Page scope was passed. The unscoped path — every Zalo
turn and any Page without assignments — then raised
"A value is required for bind parameter 'pids_active'" from SQLAlchemy before
the query ever reached Postgres.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.recommendation.repository import RecommendationRepository


def _lead():
    return SimpleNamespace(living_area=None, region=None)


def _repo():
    db = SimpleNamespace(execute=AsyncMock())
    db.execute.return_value = SimpleNamespace(fetchall=lambda: [])
    return RecommendationRepository(db), db


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("project_ids", "expected_active", "expected_pids"),
    [
        (None, False, []),
        (["11111111-2222-4333-8444-555555555555"], True, ["11111111-2222-4333-8444-555555555555"]),
    ],
)
async def test_match_jobs_always_binds_scope_parameters(
    project_ids, expected_active, expected_pids
):
    repo, db = _repo()

    await repo.match_jobs(_lead(), top_k=3, province=None, project_ids=project_ids)

    params = db.execute.await_args.args[1]
    assert params["pids_active"] is expected_active
    assert params["pids"] == expected_pids
