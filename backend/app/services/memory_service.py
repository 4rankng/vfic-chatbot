"""Memory persistence (port of VFIC Persist Memories).

greeting_gate is a VERBATIM port of the 'Should Persist?' code node (high-precision
skip of pure greetings/affirmations). canonical_key dedup uses NFD normalisation
(the live 'Dedup Facts' behavior): a fact already stored under the same canonical
key for this chat is not re-saved. Embeddings via Gemini (injected for tests).
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector import vec_literal
from app.prompts.lead_memory import MEMORY_EXTRACT_PROMPT
from app.services.memory_repository import MemoryRepository

Extractor = Callable[[str, str], Awaitable[str]]
# Batch embedder: many texts -> many vectors in one call (avoids the per-fact N+1).
BatchEmbedder = Callable[[list[str]], Awaitable[list[list[float]]]]

# Verbatim skip list from the 'Should Persist?' node.
_SKIP = {
    "ok", "okie", "oke", "okay", "okey", "yes", "no", "da", "dạ", "vang", "vâng",
    "dung", "đúng", "sai", "cam on", "cảm ơn", "cám ơn", "thank", "thanks", "hi",
    "hey", "hello", "chao", "chào", "xin chao", "xin chào", "ad", "admin",
    "👍", "👌", "😊", "😄", "🎉",
}


def greeting_gate(user_text: str) -> bool:
    """Return True if the message is substantive enough to run the memory extractor."""
    u = (user_text or "").strip().lower()
    return not (len(u) < 3 or u in _SKIP)


def canonical_key(text: str) -> str:
    """NFD-normalised, lowercased, whitespace-collapsed key for dedup."""
    return " ".join(unicodedata.normalize("NFD", (text or "").lower()).split())


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
        return _parse_facts(raw)

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

        embeddings = await embed_batch(new_facts)
        rows = [
            (
                fact,
                json.dumps({"chat_id": chat_id, "canonical_key": canonical_key(fact), "zalo_id": chat_id}),
                vec_literal(emb),
            )
            for fact, emb in zip(new_facts, embeddings)
        ]
        await repo.insert_memories(rows)
        await db.commit()
        return len(rows)

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
            return 0
        facts = await MemoryService.extract(extractor, user_text, bot_output)
        if not facts:
            return 0
        return await MemoryService.save(db, embed_batch, chat_id, facts)
