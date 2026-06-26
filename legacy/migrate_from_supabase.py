#!/usr/bin/env python3
"""One-shot ETL: live Supabase -> self-hosted Postgres (greenfield schema).

Read-only against the source (default: SUPABASE_DB_URL, schema `public`), writes to
the target (DATABASE_URL_SYNC, schema `public`, created by Alembic baseline 0001).

Run:
    python -m scripts.migrate_from_supabase --source postgresql://... --dry-run
    python -m scripts.migrate_from_supabase --source postgresql://...

Idempotent (ON CONFLICT DO NOTHING). Re-runnable. Tiny dataset (<1k rows).

Source-shape notes captured from the live catalog (2026-06-26):
  * vfic_chat_histories(id, session_id, message jsonb) has NO created_at -> we
    synthesize created_at monotonically from id (order preserved, absolute time lost).
  * message jsonb = {"type": "human"|"ai", "content": "...", ...}; a recruiter
    reply is type "human" + a recruiter_id (memory: vfic-chat-message-direction).
  * 12 distinct chat sessions but only 7 conversation rows -> we ensure a conversation
    per session_id (and per leads.zalo_id), stubbing orphans, so all 406 messages land.
  * documents rows share drive_file_id (they are really CHUNKS) -> group by
    drive_file_id: 1 knowledge_document per file, N knowledge_chunks. (All 39 live
    rows are 1 file -> 1 doc / 39 chunks.)
  * memories embedding + documents embedding copied VERBATIM (same Gemini model).
  * profiles has NO password -> users get a random temp password (printed, must reset).
  * bridge_event_log dropped (0 rows; not in target schema).
"""
from __future__ import annotations

import argparse
import json
import logging
import secrets
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.security import hash_password_sync

logger = logging.getLogger("migrate")

# Synthetic epoch for messages created_at (source has no timestamp).
BASE_EPOCH = datetime(2024, 1, 1, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Pure transform helpers (unit-testable)
# --------------------------------------------------------------------------- #
def classify_sender(message: dict) -> str:
    """Map a LangChain chat message to a message_sender enum value."""
    recruiter_id = message.get("recruiter_id") or (message.get("data") or {}).get(
        "recruiter_id"
    )
    if recruiter_id:
        return "RECRUITER"
    msg_type = str(message.get("type") or "").lower()
    if msg_type == "ai":
        return "BOT"
    if msg_type == "human":
        return "WORKER"
    return "SYSTEM"


def extract_recruiter_id(message: dict):
    return message.get("recruiter_id") or (message.get("data") or {}).get("recruiter_id")


def extract_body(message: dict) -> str:
    """Pull text content out of a LangChain message (handles str / list-of-parts / dict)."""
    content = message.get("content")
    if content is None:
        content = (message.get("data") or {}).get("content")
    if isinstance(content, list | tuple):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(part.get("text") or part.get("content") or "")
        return "".join(parts)
    if isinstance(content, dict):
        return content.get("text") or content.get("content") or json.dumps(content)
    return "" if content is None else str(content)


def synthesize_created_at(source_id: int) -> datetime:
    return BASE_EPOCH + timedelta(seconds=int(source_id))


# --------------------------------------------------------------------------- #
# Readers (source = live Supabase shape)
# --------------------------------------------------------------------------- #
def _rows(conn, sql: str):
    return [dict(r._mapping) for r in conn.execute(text(sql))]


def read_profiles(conn, s: str):
    return _rows(conn, f"SELECT id, email, full_name, role::text AS role, created_at, updated_at FROM {s}.profiles ORDER BY created_at")


def read_conversations(conn, s: str):
    return _rows(
        conn,
        f"""SELECT id, zalo_chat_id, mode::text AS mode, taken_over_at, version,
                   last_inbound_at, created_at, updated_at, assigned_recruiter_id,
                   unread_count, bot_locked_until
            FROM {s}.conversations ORDER BY created_at""",
    )


def read_chat(conn, s: str):
    return _rows(conn, f"SELECT id, session_id, message::text AS message FROM {s}.vfic_chat_histories ORDER BY id")


def read_documents(conn, s: str):
    return _rows(
        conn,
        f"""SELECT id, content, metadata::text AS metadata, embedding::text AS embedding,
                   drive_file_id, source
            FROM {s}.documents ORDER BY id""",
    )


def read_memories(conn, s: str):
    return _rows(
        conn,
        f"""SELECT id, content, metadata::text AS metadata, embedding::text AS embedding,
                   created_at
            FROM {s}.memories ORDER BY created_at""",
    )


def read_leads(conn, s: str):
    return _rows(
        conn,
        f"""SELECT id, zalo_id, name, phone, birth_year, age, living_area, address,
                   gender, region, desired_job, years_experience, latest_company,
                   expected_salary, lead_score, lead_stage, notes, created_at, updated_at
            FROM {s}.leads ORDER BY id""",
    )


def read_bot_runs(conn, s: str):
    return _rows(
        conn,
        f"""SELECT id, conversation_id, started_at, ended_at, version_at_start,
                   proposed_reply, outcome
            FROM {s}.bot_runs ORDER BY id""",
    )


def _simple_copy(conn, s: str, table: str, cols: list[str], text_cols: set[str] = frozenset(), order: str = "id"):
    sel = ", ".join(f"{c}::text" if c in text_cols else c for c in cols)
    return _rows(conn, f"SELECT {sel} FROM {s}.{table} ORDER BY {order}")


# Bus graph column lists (live == target, verbatim copy)
BUS_PROJECTS_COLS = ["id", "slug", "name", "created_at"]
BUS_COMPANIES_COLS = ["id", "project_id", "name", "aliases", "created_at"]
BUS_KS_COLS = [
    "id", "project_id", "company_id", "source_name", "source_type", "document_type",
    "source_ref", "version", "status", "metadata", "created_at", "updated_at",
]
BUS_ROUTES_COLS = [
    "id", "project_id", "company_id", "knowledge_source_id", "route_name", "route_no",
    "route_variant", "shift", "direction", "area", "mode", "source_page", "notes",
    "metadata", "created_at", "route_group_key",
]
BUS_STOPS_COLS = [
    "id", "route_id", "stop_order", "stop_name", "stop_aliases", "scheduled_time",
    "raw_stop_text", "created_at",
]
BUS_SVC_COLS = [
    "id", "project_id", "company_id", "knowledge_source_id", "route_group_key",
    "route_group_name", "day_group", "day_label", "service_type", "availability_code",
    "metadata", "created_at",
]


# --------------------------------------------------------------------------- #
# Writers (target = greenfield schema), all ON CONFLICT DO NOTHING
# --------------------------------------------------------------------------- #
def _insertmany(
    conn,
    table: str,
    cols: list[str],
    rows: list[dict],
    conflict: str,
    overriding_system: bool = False,
    jsonb_cols: set[str] = frozenset(),
) -> int:
    if not rows:
        return 0
    col_csv = ", ".join(cols)
    parts = [(f"(:{c})::jsonb" if c in jsonb_cols else f":{c}") for c in cols]
    placeholders = ", ".join(parts)
    override = " OVERRIDING SYSTEM VALUE" if overriding_system else ""
    sql = (
        f"INSERT INTO public.{table} ({col_csv}){override} VALUES ({placeholders}) "
        f"ON CONFLICT {conflict} DO NOTHING"
    )
    result = conn.execute(text(sql), rows)
    return result.rowcount or 0


BUS_TABLE_JSONB = {
    "knowledge_sources": {"metadata"},
    "bus_routes": {"metadata"},
    "bus_route_service_days": {"metadata"},
}


def write_bus_graph(conn, source_engine: Engine, s: str) -> dict:
    counts = {}
    with source_engine.connect() as src:
        for table, cols, conflict in [
            ("projects", BUS_PROJECTS_COLS, "(id)"),
            ("companies", BUS_COMPANIES_COLS, "(id)"),
            ("knowledge_sources", BUS_KS_COLS, "(id)"),
            ("bus_routes", BUS_ROUTES_COLS, "(id)"),
            ("bus_stops", BUS_STOPS_COLS, "(id)"),
            ("bus_route_service_days", BUS_SVC_COLS, "(id)"),
        ]:
            jb = BUS_TABLE_JSONB.get(table, set())
            rows = _simple_copy(src, s, table, cols, text_cols=jb, order="created_at" if "created_at" in cols else "id")
            n = _insertmany(conn, table, cols, rows, conflict, jsonb_cols=jb)
            counts[table] = n
    return counts


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run_migration(
    source_engine: Engine,
    target_engine: Engine,
    source_schema: str = "public",
    dry_run: bool = False,
) -> dict:
    """Run the full ETL. Returns a dict of per-target-table inserted counts."""
    counts: dict[str, int] = {}
    temp_passwords: dict[str, str] = {}

    with source_engine.connect() as src, target_engine.begin() as dst:
        # 1. Bus graph (parents first)
        logger.info("migrating bus graph...")
        counts.update(write_bus_graph(dst, source_engine, source_schema))

        # 2. profiles -> users (reset password)
        profiles = read_profiles(src, source_schema)
        user_rows = []
        for p in profiles:
            tmp = secrets.token_urlsafe(12)
            temp_passwords[p["email"] or str(p["id"])] = tmp
            user_rows.append({
                "id": p["id"],
                "email": (p["email"] or "").strip().lower(),
                "password_hash": hash_password_sync(tmp),
                "full_name": p["full_name"],
                "role": p["role"],
                "disabled": False,
                "created_at": p["created_at"],
                "updated_at": p["updated_at"],
            })
        counts["users"] = _insertmany(dst, "users", ["id", "email", "password_hash", "full_name", "role", "disabled", "created_at", "updated_at"], user_rows, "(id)")

        # 3. conversations: real rows first (preserve id for bot_runs FK), then stubs
        real_convs = read_conversations(src, source_schema)
        conv_rows = []
        real_zalo = set()
        for c in real_convs:
            real_zalo.add(c["zalo_chat_id"])
            mode = (c["mode"] or "bot").upper()
            if mode not in ("BOT", "HUMAN", "CLOSED"):
                mode = "BOT"
            conv_rows.append({
                "id": c["id"],
                "zalo_chat_id": c["zalo_chat_id"],
                "mode": mode,
                "status": "OPEN",
                "needs_human": False,
                "version": c["version"],
                "taken_over_at": c["taken_over_at"],
                "assigned_recruiter_id": c["assigned_recruiter_id"],
                "unread_count": c["unread_count"],
                "bot_locked_until": None,  # cleared per plan
                "last_inbound_at": c["last_inbound_at"],
                "last_outbound_at": None,
                "created_at": c["created_at"],
                "updated_at": c["updated_at"],
            })
        counts["conversations_real"] = _insertmany(
            dst, "conversations",
            ["id", "zalo_chat_id", "mode", "status", "needs_human", "version", "taken_over_at", "assigned_recruiter_id", "unread_count", "bot_locked_until", "last_inbound_at", "last_outbound_at", "created_at", "updated_at"],
            conv_rows, "(id)",
        )

        # gather every zalo_chat_id that needs a conversation row
        needed_zalo: set[str] = set(real_zalo)
        needed_zalo.update(r["session_id"] for r in read_chat(src, source_schema))
        leads = read_leads(src, source_schema)
        needed_zalo.update(lead["zalo_id"] for lead in leads if lead["zalo_id"])
        # memories zalo_id (no FK in target, but keep conversations consistent)
        for m in read_memories(src, source_schema):
            try:
                md = json.loads(m["metadata"]) if m["metadata"] else {}
            except json.JSONDecodeError:
                md = {}
            if md.get("zalo_id"):
                needed_zalo.add(md["zalo_id"])

        # stub conversations for any zalo not already present
        existing = {r[0] for r in dst.execute(text("SELECT zalo_chat_id FROM public.conversations")).all()}
        stub_zalo = [z for z in needed_zalo if z not in existing]
        stub_rows = [{
            "zalo_chat_id": z, "mode": "BOT", "status": "OPEN", "needs_human": False,
            "version": 1, "unread_count": 0,
        } for z in stub_zalo]
        counts["conversations_stub"] = _insertmany(
            dst, "conversations", ["zalo_chat_id", "mode", "status", "needs_human", "version", "unread_count"],
            stub_rows, "(zalo_chat_id)",
        )
        counts["conversations_total"] = len(real_zalo) + len(stub_zalo)

        # zalo_chat_id -> conversation id map (for messages + referential sanity)
        conv_id_by_zalo = {r.zalo_chat_id: r.id for r in dst.execute(
            text("SELECT id, zalo_chat_id FROM public.conversations")
        ).all()}

        # 4. vfic_chat_histories -> messages (synthesize created_at from id)
        message_rows = []
        skipped_chat = 0
        for row in read_chat(src, source_schema):
            cid = conv_id_by_zalo.get(row["session_id"])
            if cid is None:  # should not happen after stubbing, but be safe
                skipped_chat += 1
                continue
            try:
                msg = json.loads(row["message"]) if row["message"] else {}
            except json.JSONDecodeError:
                msg = {}
            recruiter_id = extract_recruiter_id(msg)
            message_rows.append({
                "id": row["id"],
                "conversation_id": cid,
                "sender": classify_sender(msg),
                "body": extract_body(msg),
                "recruiter_id": recruiter_id,
                "bot_run_id": None,
                "delivery_status": "SENT",
                "zalo_message_id": None,
                "external_error": None,
                "created_at": synthesize_created_at(row["id"]),
            })
        counts["messages"] = _insertmany(
            dst, "messages",
            ["id", "conversation_id", "sender", "body", "recruiter_id", "bot_run_id", "delivery_status", "zalo_message_id", "external_error", "created_at"],
            message_rows, "(id)", overriding_system=True,
        )

        # 5. documents -> knowledge_documents (group by drive_file_id) + knowledge_chunks
        docs = read_documents(src, source_schema)
        # group: key = drive_file_id if present else "id:" + id
        groups: dict[str, list[dict]] = {}
        for d in docs:
            key = d["drive_file_id"] or f"id:{d['id']}"
            groups.setdefault(key, []).append(d)
        kdoc_rows, kchunk_rows = [], []
        for key, rows in groups.items():
            first = rows[0]
            try:
                meta = json.loads(first["metadata"]) if first["metadata"] else {}
            except json.JSONDecodeError:
                meta = {}
            doc_id = first["id"]
            kdoc_rows.append({
                "id": doc_id,
                "drive_file_id": first["drive_file_id"],
                "file_name": meta.get("file_name") or first["drive_file_id"] or key,
                "source": first["source"] or "google_drive",
                "version": meta.get("version"),
                "status": "APPROVED",
                "raw_text": first["content"],
                "metadata": json.dumps(meta),
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            })
            for idx, d in enumerate(rows):
                try:
                    cmeta = json.loads(d["metadata"]) if d["metadata"] else {}
                except json.JSONDecodeError:
                    cmeta = {}
                kchunk_rows.append({
                    "document_id": doc_id,
                    "chunk_index": idx,
                    "content": d["content"] or "",
                    "embedding": d["embedding"],
                    "metadata": json.dumps(cmeta),
                    "created_at": datetime.now(timezone.utc),
                })
        counts["knowledge_documents"] = _insertmany(
            dst, "knowledge_documents",
            ["id", "drive_file_id", "file_name", "source", "version", "status", "raw_text", "metadata", "created_at", "updated_at"],
            kdoc_rows, "(id)", jsonb_cols={"metadata"},
        )
        # cast embedding/metadata in chunks
        _write_chunks(dst, kchunk_rows)
        counts["knowledge_chunks"] = len(kchunk_rows)

        # 6. memories -> verbatim (generated cols excluded; metadata drives them)
        memories = read_memories(src, source_schema)
        mem_rows = [{
            "id": m["id"], "content": m["content"],
            "metadata": m["metadata"], "embedding": m["embedding"],
            "created_at": m["created_at"],
        } for m in memories]
        _write_memories(dst, mem_rows)
        counts["memories"] = len(mem_rows)

        # 7. leads (status dropped; lead_stage null -> NEW; intent_score NULL)
        lead_rows = []
        for lead in leads:
            stage = (lead["lead_stage"] or "NEW").upper()
            score = (lead["lead_score"] or "").lower() or None
            lead_rows.append({
                "zalo_id": lead["zalo_id"], "name": lead["name"], "phone": lead["phone"],
                "birth_year": lead["birth_year"], "age": lead["age"], "living_area": lead["living_area"],
                "address": lead["address"], "gender": lead["gender"], "region": lead["region"],
                "desired_job": lead["desired_job"], "years_experience": lead["years_experience"],
                "latest_company": lead["latest_company"], "expected_salary": lead["expected_salary"],
                "lead_score": score, "lead_stage": stage, "notes": lead["notes"],
                "created_at": lead["created_at"], "updated_at": lead["updated_at"],
            })
        # ensure conversation exists for each lead zalo (already stubbed above)
        counts["leads"] = _insertmany(
            dst, "leads",
            ["zalo_id", "name", "phone", "birth_year", "age", "living_area", "address", "gender", "region", "desired_job", "years_experience", "latest_company", "expected_salary", "lead_score", "lead_stage", "notes", "created_at", "updated_at"],
            lead_rows, "(zalo_id)",
        )

        # 8. bot_runs (outcome upper)
        bot_runs = read_bot_runs(src, source_schema)
        br_rows = []
        for b in bot_runs:
            outcome = (b["outcome"] or "").upper()
            if outcome not in ("SENT", "SUPPRESSED", "ERROR"):
                outcome = "ERROR"
            br_rows.append({
                "id": b["id"],
                "conversation_id": b["conversation_id"],
                "started_at": b["started_at"], "ended_at": b["ended_at"],
                "version_at_start": b["version_at_start"],
                "proposed_reply": b["proposed_reply"], "outcome": outcome,
            })
        counts["bot_runs"] = _insertmany(
            dst, "bot_runs",
            ["id", "conversation_id", "started_at", "ended_at", "version_at_start", "proposed_reply", "outcome"],
            br_rows, "(id)", overriding_system=True,
        )
        counts["_skipped_chat_orphans"] = skipped_chat

    if temp_passwords:
        logger.warning("TEMP passwords issued for migrated users (reset on first login):")
        for email, pw in temp_passwords.items():
            logger.warning("  %s -> %s", email, pw)

    return counts


def _write_chunks(dst, rows: list[dict]) -> None:
    if not rows:
        return
    sql = text(
        "INSERT INTO public.knowledge_chunks "
        "(document_id, chunk_index, content, embedding, metadata, created_at) "
        "VALUES (:document_id, :chunk_index, :content, (:embedding)::vector, (:metadata)::jsonb, :created_at) "
        "ON CONFLICT (document_id, chunk_index) DO NOTHING"
    )
    dst.execute(sql, rows)


def _write_memories(dst, rows: list[dict]) -> None:
    if not rows:
        return
    sql = text(
        "INSERT INTO public.memories (id, content, metadata, embedding, created_at) "
        "VALUES (:id, :content, (:metadata)::jsonb, (:embedding)::vector, :created_at) "
        "ON CONFLICT (id) DO NOTHING"
    )
    dst.execute(sql, rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate live Supabase -> self-hosted Postgres.")
    parser.add_argument("--source", default=None, help="Source Postgres DSN (default: $SUPABASE_DB_URL)")
    parser.add_argument("--source-schema", default="public")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    source_dsn = args.source or __import__("os").environ.get("SUPABASE_DB_URL")
    if not source_dsn:
        print("error: --source or $SUPABASE_DB_URL is required", file=sys.stderr)
        return 2

    from app.core.config import get_settings

    target_dsn = get_settings().database_url_sync
    source_engine = create_engine(source_dsn)
    target_engine = create_engine(target_dsn)

    if args.dry_run:
        with source_engine.connect() as src:
            for label, sql in [
                ("profiles", f"SELECT count(*) FROM {args.source_schema}.profiles"),
                ("conversations", f"SELECT count(*) FROM {args.source_schema}.conversations"),
                ("vfic_chat_histories", f"SELECT count(*) FROM {args.source_schema}.vfic_chat_histories"),
                ("documents", f"SELECT count(*) FROM {args.source_schema}.documents"),
                ("memories", f"SELECT count(*) FROM {args.source_schema}.memories"),
                ("leads", f"SELECT count(*) FROM {args.source_schema}.leads"),
                ("bot_runs", f"SELECT count(*) FROM {args.source_schema}.bot_runs"),
            ]:
                logger.info("dry-run %s = %s", label, src.execute(text(sql)).scalar())
        return 0

    counts = run_migration(source_engine, target_engine, source_schema=args.source_schema)
    logger.info("migration complete: %s", json.dumps(counts, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
