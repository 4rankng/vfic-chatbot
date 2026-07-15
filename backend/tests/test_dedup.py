from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.dedup import MessageDedupService


@pytest.mark.asyncio
async def test_claim_commits_after_inserting_dedup_marker():
    db = MagicMock()
    db.commit = AsyncMock()
    repo = MagicMock()
    repo.delete_expired = AsyncMock()
    repo.insert_claim = AsyncMock(return_value=1)

    with patch("app.services.dedup.MessageDedupRepository", return_value=repo):
        claimed = await MessageDedupService.claim(db, "chat", "hash")

    assert claimed is True
    db.commit.assert_awaited_once()
