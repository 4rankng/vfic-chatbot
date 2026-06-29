"""Memory persistence (port of VFIC Persist Memories).

greeting_gate is a VERBATIM port of the 'Should Persist?' code node (high-precision
skip of pure greetings/affirmations). canonical_key dedup is accent-insensitive:
a fact already stored under the same canonical key for this chat is not re-saved.
Embeddings via Gemini are injected for tests.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embedding import embed_with_fallback
from app.core.text import normalize_vietnamese_text
from app.core.vector import vec_literal
from app.prompts.lead_memory import MEMORY_EXTRACT_PROMPT
from app.services.memory_repository import MemoryRepository

Extractor = Callable[[str, str], Awaitable[str]]
# Batch embedder: many texts -> many vectors in one call (avoids the per-fact N+1).
BatchEmbedder = Callable[[list[str]], Awaitable[list[list[float]]]]
logger = logging.getLogger(__name__)

# Verbatim skip list from the 'Should Persist?' node.
_SKIP = {
    "ok", "okie", "oke", "okay", "okey", "yes", "no", "da", "dạ", "vang", "vâng",
    "dung", "đúng", "sai", "cam on", "cảm ơn", "cám ơn", "thank", "thanks", "hi",
    "hey", "hello", "chao", "chào", "xin chao", "xin chào", "ad", "admin",
    "👍", "👌", "😊", "😄", "🎉",
}


def greeting_gate(user_text: str) -> bool:
    """Return True if the message is substantive enough to run the memory extractor.

    Allows single meaningful answers like '5' (age), '25', '30' through — these
    are numeric responses that carry information even though they're short.
    """
    u = (user_text or "").strip().lower()
    if not u:
        return False
    if len(u) < 3:
        # Allow single/double-digit numeric answers (e.g. "5" = age).
        return u.isdigit()
    return u not in _SKIP


def canonical_key(text: str) -> str:
    """Accent-insensitive, lowercased, whitespace-collapsed key for dedup."""
    return normalize_vietnamese_text(text or "")


def _flatten_facts(raw) -> list[str]:
    """Normalise an LLM fact payload into a flat list of non-empty string facts.

    MiniMax sometimes returns a list of OBJECTS (e.g. [{"fact": "..."}]) instead of
    a list of strings; naively ``str()``-ing those reproduces the legacy
    '[object Object]' bug. Walk dicts/lists and keep only human-readable strings.
    """
    out: list[str] = []

    def walk(node) -> None:
        if isinstance(node, str):
            t = node.strip()
            if t:
                out.append(t)
        elif isinstance(node, dict):
            picked = [node[k] for k in ("fact", "facts", "text", "content", "memory", "value") if k in node]
            items = picked if picked else list(node.values())
            for v in items:
                walk(v)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(raw)
    return out


def _parse_facts(raw) -> list[str]:
    if isinstance(raw, (list, tuple, dict)):
        return _flatten_facts(raw)
    s = str(raw if raw is not None else "").strip()
    s = re.sub(r"^\s*```(?:json)?", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"```\s*$", "", s, flags=re.IGNORECASE).strip()
    m = re.search(r"\[[\s\S]*\]", s)
    if not m:
        return []
    try:
        parsed = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return []
    return _flatten_facts(parsed)


class MemoryService:
    @staticmethod
    async def extract(extractor: Extractor, user_text: str, bot_output: str) -> list[str]:
        raw = await extractor(MEMORY_EXTRACT_PROMPT, f"Tin nhắn người dùng: {user_text or ''}\n\nPhản hồi của bot: {bot_output or ''}")
        facts = _parse_facts(raw)
        logger.debug("memory extract: %d facts from user text (%d chars)", len(facts), len(user_text or ""))
        return facts

    @staticmethod
    async def _embed_facts(embed_batch: BatchEmbedder, facts: list[str]) -> list[list[float]]:
        return await embed_with_fallback(embed_batch, facts, label="memory embedder")

    @staticmethod
    async def save(db: AsyncSession, embed_batch: BatchEmbedder, chat_id: str, facts: list[str]) -> int:
        repo = MemoryRepository(db)
        existing = await repo.fetch_canonical_keys(chat_id)

        # Dedup first (intra-batch + vs stored), then ONE batched embed + ONE
        # executemany INSERT. Previously this looped embedder()+INSERT per fact (N+N).
        new_facts: list[str] = []
        for fact in facts:
            ck = canonical_key(fact)
            if ck and ck not in existing:
                existing.add(ck)
                new_facts.append(fact)
        if not new_facts:
            await db.commit()
            return 0

        embeddings = await MemoryService._embed_facts(embed_batch, new_facts)
        rows = [
            (
                fact,
                json.dumps({"chat_id": chat_id, "canonical_key": canonical_key(fact), "zalo_id": chat_id}),
                vec_literal(emb),
            )
            for fact, emb in zip(new_facts, embeddings)
        ]
        inserted = await repo.insert_memories(rows)
        await db.commit()
        logger.debug("memory save: %d new facts persisted for chat %s", inserted, chat_id)
        return inserted

    @staticmethod
    async def persist(
        db: AsyncSession,
        embed_batch: BatchEmbedder,
        extractor: Extractor,
        chat_id: str,
        user_text: str,
        bot_output: str,
    ) -> int:
        if not greeting_gate(user_text):
            logger.debug("memory persist skipped by greeting_gate: '%s'", user_text[:80])
            return 0
        facts = await MemoryService.extract(extractor, user_text, bot_output)
        if not facts:
            return 0
        try:
            return await MemoryService.save(db, embed_batch, chat_id, facts)
        except Exception:
            logger.warning(
                "memory persist failed for chat %s (%d facts extracted); chat turn continues",
                chat_id, len(facts), exc_info=True,
            )
            return 0
