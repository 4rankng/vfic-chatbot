"""First-touch candidate attribution against real PostgreSQL.

The merge rule is pure (unit-tested in ``tests/test_candidate_attribution.py``);
what needs a database is the part that can silently lose data: the write riding
the inbound transaction, first touch surviving later touches, and the
referral-only stamp committing on its own.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.conversation import Conversation
from app.schemas.conversation import ConversationOut
from app.services.conversation.repository import ConversationRepository
from app.services.conversation.state import ConversationState

pytestmark = pytest.mark.integration

PROVIDER = "facebook_messenger"
ACCOUNT = "page-1"


class _RecordingEvents:
    def __init__(self) -> None:
        self.created = 0
        self.updated = 0

    async def message_created(self, *args, **kwargs) -> None:
        self.created += 1

    async def conversation_updated(self, *args, **kwargs) -> None:
        self.updated += 1


def _state(session) -> ConversationState:
    return ConversationState(session, ConversationRepository(session), _RecordingEvents())


async def _reload(session, conv_id) -> Conversation:
    return (await session.scalars(select(Conversation).where(Conversation.id == conv_id))).one()


@pytest.mark.asyncio
async def test_inbound_attribution_persists_and_first_touch_survives(
    integration_session,
) -> None:
    state = _state(integration_session)
    conv = await state.ensure_by_identity(
        provider="zalo_oa",
        account_key="tingting",
        external_id="attribution-user",
        zalo_chat_id_alias="oa:tingting:attribution-user",
        zalo_channel_alias="oa",
    )

    await state.record_inbound(
        conv,
        body="#BV1026 muon hoi viec lam",
        provider_message_id="attr-1",
        attribution={"kind": "post_link", "post_code": "BV1026"},
    )
    stored = await _reload(integration_session, conv.id)
    assert stored.attribution == {"kind": "post_link", "post_code": "BV1026"}

    # An ordinary later message must not touch the record.
    await state.record_inbound(conv, body="sau nhe", provider_message_id="attr-2")
    stored = await _reload(integration_session, conv.id)
    assert stored.attribution == {"kind": "post_link", "post_code": "BV1026"}

    # Neither may a competing code from a second link — first touch wins.
    await state.record_inbound(
        conv,
        body="#OTHER1 hoi them",
        provider_message_id="attr-3",
        attribution={"kind": "post_link", "post_code": "OTHER1"},
    )
    stored = await _reload(integration_session, conv.id)
    assert stored.attribution == {"kind": "post_link", "post_code": "BV1026"}

    # The recruiter API projects the same record.
    assert ConversationOut.model_validate(stored).attribution == {
        "kind": "post_link",
        "post_code": "BV1026",
    }


@pytest.mark.asyncio
async def test_referral_stamp_then_ad_message_completes_the_record(
    integration_session,
) -> None:
    """Messenger: Get Started stamps the ref, the ad's ids arrive with the text."""
    state = _state(integration_session)
    conv = await state.ensure_by_identity(
        provider=PROVIDER,
        account_key=ACCOUNT,
        external_id="psid-attr-1",
        zalo_chat_id_alias=None,
        zalo_channel_alias="facebook_messenger",
    )

    # Referral-only event: no message exists, so this commits its own write.
    await state.stamp_attribution(
        conv,
        {"kind": "referral", "post_code": "post_202610", "referral_source": "SHORTLINK"},
    )
    stored = await _reload(integration_session, conv.id)
    assert stored.attribution == {
        "kind": "referral",
        "post_code": "post_202610",
        "referral_source": "SHORTLINK",
    }

    await state.record_inbound(
        conv,
        body="minh quan tam vi tri nay",
        provider_message_id="attr-psid-1",
        attribution={
            "kind": "referral",
            "ad_id": "1234567890",
            "post_id": "111_222",
            "referral_source": "ADS",
        },
    )
    stored = await _reload(integration_session, conv.id)
    assert stored.attribution == {
        "kind": "referral",
        "post_code": "post_202610",
        "referral_source": "SHORTLINK",
        "ad_id": "1234567890",
        "post_id": "111_222",
    }


@pytest.mark.asyncio
async def test_inbound_without_attribution_leaves_the_column_null(
    integration_session,
) -> None:
    """No source means no write — a NULL stays NULL, never an empty object."""
    state = _state(integration_session)
    conv = await state.ensure_by_identity(
        provider=PROVIDER,
        account_key=ACCOUNT,
        external_id="psid-attr-2",
        zalo_chat_id_alias=None,
        zalo_channel_alias="facebook_messenger",
    )

    await state.record_inbound(conv, body="chao mung ban", provider_message_id="attr-plain")

    stored = await _reload(integration_session, conv.id)
    assert stored.attribution is None
    assert ConversationOut.model_validate(stored).attribution is None
