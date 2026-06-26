"""US-007 MemoryService tests: greeting-gate (verbatim 'Should Persist?' skip list),
NFD canonical-key dedup, and save (DB-backed with an injected batch embedder)."""
import uuid

import pytest

from app.services.memory_service import MemoryService, canonical_key, greeting_gate

pytestmark = pytest.mark.asyncio


async def _emb_batch(texts):
    # Batch embedder fixture: one call per save(), returns one vector per text.
    return [[0.01] * 3072 for _ in texts]


async def _ext(_system, _user):
    return '[]'


def _chat_id() -> str:
    # Unique per test/run so save-tests are repeatable on the persistent dev DB.
    return f"mem-test-{uuid.uuid4().hex[:8]}"


def test_greeting_gate_skips_pure_greetings():
    assert greeting_gate("chào") is False
    assert greeting_gate("ok") is False
    assert greeting_gate("dạ") is False
    assert greeting_gate("hi") is False
    assert greeting_gate("ab") is False  # < 3 chars
    assert greeting_gate("Tôi tên Dũng, muốn tìm việc ở Hải Phòng") is True


def test_canonical_key_nfd_dedup():
    a = canonical_key("Người dùng tên là Dũng")
    b = canonical_key("người  dùng  tên là Dũng")
    assert a == b


async def test_save_then_dedup(db_session):
    chat_id = _chat_id()
    facts = ["Người dùng tên là Dũng", "Muốn làm việc ở Hải Phòng"]
    n1 = await MemoryService.save(db_session, _emb_batch, chat_id, facts)
    assert n1 == 2
    # re-saving the same facts -> all deduped via canonical_key
    n2 = await MemoryService.save(db_session, _emb_batch, chat_id, facts)
    assert n2 == 0


async def test_save_dedups_intra_batch(db_session):
    # duplicate facts within one batch are stored once
    facts = ["Muốn làm việc ở Hải Phòng", "muốn  làm việc ở hải phòng"]
    n = await MemoryService.save(db_session, _emb_batch, _chat_id(), facts)
    assert n == 1


async def test_persist_gated_on_greeting(db_session):
    # a pure greeting never reaches the extractor
    n = await MemoryService.persist(db_session, _emb_batch, _ext, _chat_id(), "chào", "")
    assert n == 0
