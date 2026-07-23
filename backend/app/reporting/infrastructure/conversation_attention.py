"""SQLAlchemy adapter for the conversation attention read model."""

from __future__ import annotations


class SqlAlchemyConversationAttentionAdapter:
    def __init__(self, db, viewer) -> None:
        self._db = db
        self._viewer = viewer

    async def attention_reason_page(
        self,
        *,
        reason: str,
        channel_provider: str | None,
        page: int,
        per_page: int,
    ):
        from app.models.user import Role
        from app.services.dashboard.repository import DashboardRepository

        recruiter_id = None if self._viewer.role == Role.admin else str(self._viewer.id)
        return await DashboardRepository(self._db).attention_reason_page(
            recruiter_id,
            reason=reason,
            channel_provider=channel_provider,
            page=page,
            per_page=per_page,
        )

    async def visible_conversations(self, ids):
        from app.services.conversation.repository import ConversationRepository

        return await ConversationRepository(self._db).get_visible_by_ids(
            viewer=self._viewer,
            ids=ids,
        )


__all__ = ["SqlAlchemyConversationAttentionAdapter"]
