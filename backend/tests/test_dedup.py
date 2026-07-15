from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.dedup import MessageDedupService


@pytest.mark.asyncio
async def test_claim_can_remain_uncommitted_for_composite_transaction():
    db = MagicMock()
    db.commit = AsyncMock()
    repo = MagicMock()
    repo.delete_expired = AsyncMock()
    repo.insert_claim = AsyncMock(return_value=1)

    with patch("app.services.dedup.MessageDedupRepository", return_value=repo):
        claimed = await MessageDedupService.claim(db, "chat", "hash", commit=False)

    assert claimed is True
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_claim_commits_by_default():
    db = MagicMock()
    db.commit = AsyncMock()
    repo = MagicMock()
    repo.delete_expired = AsyncMock()
    repo.insert_claim = AsyncMock(return_value=1)

    with patch("app.services.dedup.MessageDedupRepository", return_value=repo):
        claimed = await MessageDedupService.claim(db, "chat", "hash")

    assert claimed is True
    db.commit.assert_awaited_once()
