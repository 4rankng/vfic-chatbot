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

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector import vec_literal
from app.graph.lead_memory_prompts import MEMORY_EXTRACT_PROMPT

Extractor = Callable[[str, str], Awaitable[str]]
Embedder = Callable[[str], Awaitable[list[float]]]

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
    async def save(db: AsyncSession, embedder: Embedder, chat_id: str, facts: list[str]) -> int:
        rows = (
            await db.execute(
                text("SELECT metadata->>'canonical_key' AS ck FROM memories WHERE metadata->>'chat_id' = :c"),
                {"c": chat_id},
            )
        ).all()
        existing = {r.ck for r in rows if r.ck}

        saved = 0
        for fact in facts:
            ck = canonical_key(fact)
            if not ck or ck in existing:
                continue
            emb = vec_literal(await embedder(fact))
            await db.execute(
                text(
                    "INSERT INTO memories(content, metadata, embedding) "
                    "VALUES (:c, CAST(:m AS jsonb), CAST(:e AS vector))"
                ),
                {
                    "c": fact,
                    "m": json.dumps({"chat_id": chat_id, "canonical_key": ck, "zalo_id": chat_id}),
                    "e": emb,
                },
            )
            existing.add(ck)
            saved += 1
        await db.commit()
        return saved

    @staticmethod
    async def persist(db: AsyncSession, embedder: Embedder, extractor: Extractor, chat_id: str, user_text: str, bot_output: str) -> int:
        if not greeting_gate(user_text):
            return 0
        facts = await MemoryService.extract(extractor, user_text, bot_output)
        if not facts:
            return 0
        return await MemoryService.save(db, embedder, chat_id, facts)
