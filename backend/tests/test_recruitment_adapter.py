import pytest

from app.services.knowledge.publishing.publisher import PublishingError
from app.services.ingestion.recruitment_adapter import resolve_stable_job_id


async def test_recruitment_adapter_rejects_missing_or_non_uuid_job_identity():
    with pytest.raises(PublishingError, match="explicit job_id"):
        await resolve_stable_job_id(None, project_id=None, job_id=None)  # type: ignore[arg-type]
    with pytest.raises(PublishingError, match="must be a UUID"):
        await resolve_stable_job_id(None, project_id=None, job_id="welder")  # type: ignore[arg-type]
