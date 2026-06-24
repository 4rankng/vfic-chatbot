"""US-007 MemoryService tests: greeting-gate (verbatim 'Should Persist?' skip list),
NFD canonical-key dedup, and save (DB-backed with an injected embedder)."""
import pytest

from app.services.memory_service import MemoryService, canonical_key, greeting_gate

pytestmark = pytest.mark.asyncio


async def _emb(_text):
    return [0.01] * 3072


async def _ext(_system, _user):
    return '[]'


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
    facts = ["Người dùng tên là Dũng", "Muốn làm việc ở Hải Phòng"]
    n1 = await MemoryService.save(db_session, _emb, "mem-1", facts)
    assert n1 == 2
    # re-saving the same facts -> all deduped via canonical_key
    n2 = await MemoryService.save(db_session, _emb, "mem-1", facts)
    assert n2 == 0


async def test_persist_gated_on_greeting(db_session):
    # a pure greeting never reaches the extractor
    n = await MemoryService.persist(db_session, _emb, _ext, "mem-2", "chào", "")
    assert n == 0
