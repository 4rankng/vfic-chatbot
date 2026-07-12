import pytest
from pydantic import ValidationError

from app.models.lead import LeadStage
from app.schemas.auth import LoginRequest
from app.schemas.conversation import SendMessageRequest
from app.schemas.job import JobSearchRequest, JobUpdate
from app.schemas.knowledge import KnowledgeDocumentUpdate, SearchTestRequest, UploadRequest
from app.schemas.lead import AssignRequest, FollowUpCreate, LeadUpdate, StageRequest
from app.schemas.personas import PersonaCreate, PersonaUpdate
from app.schemas.projects import FeatureUpdate, ProjectCreate, ProjectUpdate
from app.schemas.user import SelfProfileUpdate, UserCreate, UserUpdate


@pytest.mark.parametrize(
    "schema, payload",
    [
        (LeadUpdate, {"unknown_field": "value"}),
        (ProjectUpdate, {"id": "8d833c84-1a4a-4ab2-a358-4f8ef1563b7b"}),
        (FeatureUpdate, {"display_priority": 1}),
        (KnowledgeDocumentUpdate, {"status": "PUBLISHED"}),
        (PersonaUpdate, {"is_active": True}),
        (JobUpdate, {"company_id": "8d833c84-1a4a-4ab2-a358-4f8ef1563b7b"}),
        (UserUpdate, {"password": "not-here"}),
        (SelfProfileUpdate, {"role": "admin"}),
    ],
)
def test_update_schemas_reject_unknown_fields(schema, payload):
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_lead_update_accepts_stage_changes():
    body = LeadUpdate.model_validate({"lead_stage": "SKIPPED"})

    assert body.lead_stage == LeadStage.SKIPPED


@pytest.mark.parametrize(
    "schema, payload",
    [
        (LoginRequest, {"email": "a@example.com", "password": "pw", "remember": True}),
        (SendMessageRequest, {"body": "hello", "lead_stage": "SKIPPED"}),
        (AssignRequest, {"recruiter_id": "8d833c84-1a4a-4ab2-a358-4f8ef1563b7b", "role": "admin"}),
        (StageRequest, {"stage": "SKIPPED", "lead_stage": "NEW"}),
        (FollowUpCreate, {"due_at": "2030-01-01T00:00:00Z", "status": "DONE"}),
        (ProjectCreate, {"slug": "lg", "name": "LG", "id": "8d833c84-1a4a-4ab2-a358-4f8ef1563b7b"}),
        (PersonaCreate, {"name": "Agent", "body_md": "Body", "created_by": "me"}),
        (
            UserCreate,
            {
                "email": "a@example.com",
                "password": "password123",
                "confirm_password": "password123",
            },
        ),
        (UploadRequest, {"file_name": "a.md", "content": "body", "status": "PUBLISHED"}),
        (SearchTestRequest, {"query": "x", "filters": {}}),
        (JobSearchRequest, {"query": "x", "stage": "NEW"}),
    ],
)
def test_request_schemas_reject_unknown_fields(schema, payload):
    with pytest.raises(ValidationError):
        schema.model_validate(payload)
