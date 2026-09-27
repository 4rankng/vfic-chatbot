"""Seed orchestration: truncate, then insert every fixture domain in FK order.

The numbered comments are load-bearing — the insert order is what satisfies the
foreign keys, and the flushes keep the conversation trigger (which inserts a
placeholder lead per thread) from racing the lead fixtures. The ``print`` calls
are the script's user-facing output; their order and wording are part of the
CLI surface.
"""

from __future__ import annotations

import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings

from .audit import make_audit_events
from .companies import make_companies
from .conversations import make_conversations
from .jobs import make_jobs
from .knowledge import make_knowledge_chunks, make_knowledge_documents
from .leads import (
    make_followup_tasks,
    make_lead_events,
    make_leads,
    remove_trigger_generated_leads,
)
from .messages import make_messages_and_bot_runs
from .personas import make_personas
from .projects import make_projects
from .telemetry import seed_performance_metrics
from .truncate import truncate_all
from .users import make_users
from .worker_features import make_job_feature_values, make_worker_features


def seed() -> None:
    settings = get_settings()
    url = settings.database_url_sync
    engine = create_engine(url)

    # 1. Wipe existing data
    truncate_all(engine)

    with Session(engine) as db:
        # 2. Users
        users = make_users()
        db.add_all(users)
        db.flush()
        print(f"✓ {len(users)} users")

        # 3. Projects
        projects = make_projects()
        db.add_all(projects)
        db.flush()
        print(f"✓ {len(projects)} projects")

        # 4. Personas (global; provider-scoped overrides live in adapter_persona_assignments)
        personas = make_personas(users)
        db.add_all(personas)
        db.flush()
        print(f"✓ {len(personas)} personas")

        # 5. Companies
        companies = make_companies(projects)
        db.add_all(companies)
        db.flush()
        print(f"✓ {len(companies)} companies")

        # 6. Jobs
        jobs = make_jobs(companies)
        db.add_all(jobs)
        db.flush()
        print(f"✓ {len(jobs)} jobs")

        # 7. Worker Feature Catalog
        features = make_worker_features()
        db.add_all(features)
        db.flush()
        print(f"✓ {len(features)} worker features")

        # 8. Job Feature Values
        jfvs = make_job_feature_values(projects, features)
        db.add_all(jfvs)
        db.flush()
        print(f"✓ {len(jfvs)} job feature values")

        # 9. Conversations (must be before leads — leads.zalo_id FK → conversations.zalo_chat_id)
        #    Each conversation needs its canonical Contact + channel identity (Alembic 0047).
        convos, contacts, identities = make_conversations(users)
        db.add_all(contacts)
        db.flush()
        db.add_all(identities)
        db.flush()
        db.add_all(convos)
        db.flush()
        remove_trigger_generated_leads(db, convos)
        db.flush()
        print(f"✓ {len(contacts)} contacts, {len(identities)} channel identities")
        print(f"✓ {len(convos)} conversations")

        # 10. Leads (link first 25 to conversations via zalo_id)
        leads = make_leads(users, jobs, convos)
        db.add_all(leads)
        db.flush()
        print(f"✓ {len(leads)} leads")

        # 11. Lead Events
        lead_events = make_lead_events(leads, users)
        db.add_all(lead_events)
        db.flush()
        print(f"✓ {len(lead_events)} lead events")

        # 12. Follow-up Tasks
        tasks = make_followup_tasks(leads, users)
        db.add_all(tasks)
        db.flush()
        print(f"✓ {len(tasks)} follow-up tasks")

        # 13. Messages + Bot Runs
        msgs, runs = make_messages_and_bot_runs(convos, users)
        db.add_all(msgs)
        db.flush()
        print(f"✓ {len(msgs)} messages")
        db.add_all(runs)
        db.flush()
        seed_performance_metrics(runs, msgs)
        db.flush()
        print(f"✓ {len(runs)} bot runs")
        print("✓ performance telemetry across healthy, warning, and failure paths")

        # 14. Knowledge Documents
        kdocs = make_knowledge_documents(projects)
        db.add_all(kdocs)
        db.flush()
        print(f"✓ {len(kdocs)} knowledge documents")

        # 15. Knowledge Chunks (raw SQL — embedding is vector(3072), not ORM-writable)
        kchunks = make_knowledge_chunks(kdocs)
        for chunk in kchunks:
            # Build SQL literals for complex types (psycopg text() can't adapt
            # dict/list/array). UUIDs as strings are fine since Postgres casts them.
            questions_arr = (
                "{" + ",".join(q.replace("'", "''") for q in (chunk.questions or [])) + "}"
            )
            entities_json = json.dumps(chunk.entities or {}, ensure_ascii=False)
            proj = f"'{chunk.project_id}'" if chunk.project_id else "NULL"
            db.execute(
                text(
                    f"INSERT INTO knowledge_chunks "
                    f"(id, document_id, chunk_index, content, embedding, metadata, "
                    f"project_id, source_quote, summary, questions, category, entities, "
                    f"confidence, search_text) "
                    f"VALUES ('{chunk.id}', '{chunk.document_id}', {chunk.chunk_index}, "
                    f"'{chunk.content.replace(chr(39), chr(39) + chr(39))}', "
                    f"NULL::vector(3072), '{{}}', "
                    f"{proj}, "
                    f"'{(chunk.source_quote or '').replace(chr(39), chr(39) + chr(39))}', "
                    f"'{(chunk.summary or '').replace(chr(39), chr(39) + chr(39))}', "
                    f"'{questions_arr}', "
                    f"'{(chunk.category or '').replace(chr(39), chr(39) + chr(39))}', "
                    f"'{entities_json}'::jsonb, "
                    f"'{(chunk.confidence or '').replace(chr(39), chr(39) + chr(39))}', "
                    f"'{(chunk.search_text or '').replace(chr(39), chr(39) + chr(39))}')"
                )
            )
        db.flush()
        print(f"✓ {len(kchunks)} knowledge chunks")

        # 16. Audit Events
        audit = make_audit_events(users)
        db.add_all(audit)
        db.flush()
        print(f"✓ {len(audit)} audit events")

        db.commit()
        print("\n✅ Dev database seeded successfully!")
        print("   Users: admin@vfic.dev / lan.nguyen@vfic.dev / minh.tran@vfic.dev")
        print("   Password: admin123")
        print(f"   35 leads, 25 conversations, {len(msgs)} messages across 4 projects")
