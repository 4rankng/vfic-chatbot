# Incident Runbook

Operational responses for production incidents. Add the dated section when a
new incident class is discovered; keep steps copy-pasteable.

## External-source sync shipped a bad FAQ revision

The daily auto-sync (or an admin "Xử lý ngay" click) stages and activates a
new category revision from a public Google Sheet. If the sheet contains wrong
content (a bad edit, a content-poisoning row, or a misparsed column), the bad
FAQ goes live immediately. Revisions are retained forever, so rolling back is
a re-point of the active pointer — no data is deleted.

### Detect

- Recruiters report the bot answering FAQ questions with wrong content.
- The performance dashboard (`/api/v1/admin/performance` →
  `external_source_sync`) shows a recent `last_synced_at_max`.
- `GET /api/v1/knowledge/projects/{pid}/external-sources` shows the row's
  `last_status` and `last_revision_id`.

### Stop the bleeding (auto-sync only)

If `auto_sync_enabled` is on, disable it so the next daily tick does not
re-stage the same bad content. In v1 there is no PATCH endpoint — delete +
re-create the row, or flip the flag directly:

```sql
UPDATE external_source_sync_state
SET auto_sync_enabled = false
WHERE project_id = '<project-uuid>' AND category_key = 'faq';
```

### Roll back to the prior good revision

```sql
-- 1. List the project's FAQ revisions (newest first). Pick the most recent
--    ARCHIVED revision whose content you trust (usually the one just before
--    the bad sync).
SELECT r.id, r.revision_no, r.status, r.content_sha256, r.created_at, r.activated_at
FROM knowledge_category_revisions r
JOIN knowledge_categories c ON c.id = r.category_id
WHERE c.project_id = '<project-uuid>'
  AND c.category_key = 'faq'
ORDER BY r.revision_no DESC;

-- 2. Re-point the active revision at the chosen good revision id.
UPDATE knowledge_categories
SET active_revision_id = '<chosen-revision-uuid>'
WHERE project_id = '<project-uuid>' AND category_key = 'faq';

-- 3. Mark the rolled-to revision ACTIVE and the bad one ARCHIVED so the UI
--    reflects reality.
UPDATE knowledge_category_revisions SET status = 'ACTIVE', activated_at = now()
WHERE id = '<chosen-revision-uuid>';
UPDATE knowledge_category_revisions SET status = 'ARCHIVED'
WHERE id = '<bad-revision-uuid>';
```

### Make the bot see the rollback immediately

The retrieval path caches FAQ chunks. Bump the caches (or restart the `web`
container):

```bash
# On the droplet, restart the web container to re-read the active revision.
docker compose restart web
```

A future revision will add a one-click rollback endpoint + UI; until then this
SQL path is the incident response (reversible in under two minutes).

## 2026-09-26 — Deploy worker-restart turn gap (bot silent for minutes after a deploy)

Recruiters report "the bot stopped answering"; messages show as *Received* in
Zalo with no reply, and the admin inbox shows *Bot chưa phản hồi*.

`worker-chatbot` (3 replicas) is a single stack-wide service keyed to
`${IMAGE_TAG}`, **not** per color. Every deploy recreates all three replicas at
the new tag, and the worker preloads langchain/openai + warms LLM clients
before it registers on `webhook_high` (`worker preload_imports completed in
83.2s` observed on the 1.9 GiB host; healthcheck `start_period: 60s`). Until the
first replica registers, inbound turns sit in the queue and produce no reply —
a delay, never a loss: turns enqueued during the gap run as soon as a worker
registers (2026-09-26 05:13 messages were answered at 05:18:37).

### Detect

- `docker inspect vfic-worker-chatbot-1 --format '{{.State.StartedAt}} {{.State.Health.Status}}'`
  compared with the deploy start; `/opt/vfic/ACTIVE_COLOR` + `PREV_COLOR` show a
  flip just happened.
- Worker log: `docker logs vfic-worker-chatbot-1 | grep preload_imports`.
- Queue is draining, not stuck: `docker exec vfic-redis-1 redis-cli -a "$REDIS_PASSWORD" --no-auth-warning llen rq:queue:webhook_high`.
- Delivery catch-up: `select status, attempts, last_error from outbound_outbox where message_id = <id>;`
  (rows go `PENDING` → `SENT` with `attempts = 1` once a worker is up).

### Do not misread these as the cause

- `webhook accepted while runtime inactive channel=…` is a benign legacy ack.
  `InstallationService.resolve_active()` returns `None` when
  `installation_state` is empty (0 rows in prod — the installation tables have
  never been populated there), and the turn is still enqueued with an empty
  runtime stamp; the graph then runs the legacy path.
- Both web colors reporting `unhealthy` with `Health check exceeded timeout
  (5s)` mid-deploy is host CPU/memory contention against the 5s web healthcheck
  timeout, not a code fault.

### Mitigation — implemented 2026-09-26

- `bg_deploy.sh` (and `bg_rollback.sh`) now recreate the turn worker
  (`TURN_WORKERS=worker-chatbot`) **one replica at a time** via
  `rolling_recreate_service`, waiting for a healthy replacement before removing
  the next, so `replicas - 1` keep consuming `webhook_high` throughout. The roll
  uses `up -d --no-recreate --scale <svc>=<n>`, which creates the missing
  replica and leaves the surviving containers untouched.
- A pre-flip hard gate requires at least one healthy `worker-chatbot` replica; a
  post-flip **turn-pipeline gate** (`scripts/turn_pipeline_check.py`) fails the
  deploy (and rolls back) when no live consumer is registered on
  `webhook_high`, when a `BOT`-mode conversation is waiting for a reply, or when
  a `PENDING` outbound row is older than 120 s. `/health/queue` proves workers
  *exist*; this proves work is *draining*.
- `worker-maintenance` was added to the deploy `WORKERS` list. Every service
  pinned to `${IMAGE_TAG}` in `docker-compose.yml` must be listed there.
- Web healthchecks: probe timeout 3s→10s, compose `timeout` 5s→15s, `interval`
  5s→10s (a 5s budget reported both colors `unhealthy` under deploy-time CPU
  contention and can abort a deploy mid-flip).
  `worker-chatbot` `start_period` 60s→180s (measured 83.2 s preload).
- Still open (needs a larger change): the chatbot workers are shared across
  colors, so they are still restarted on every deploy — the roll only removes
  the *gap*, not the restart. Per-color worker services would remove it
  entirely.

Also: a redeploy of an *unchanged* sha (`PREV_TAG == IMAGE_TAG`) still restarts
everything — do not re-run `make deploy` to "fix" a symptom; check the deploy
state first.

Note when reading the pipeline gate's output: RQ worker registration keys have
a TTL (`worker_ttl + 60`), so the registered-consumer count can briefly exceed
the number of live replicas after a restart. That is why the gate's threshold is
"at least one", not "exactly the replica count".

## Rotating the production Postgres password

`POSTGRES_PASSWORD` (and the password embedded in `DATABASE_URL` /
`DATABASE_URL_SYNC`) live in `/opt/vfic/.env`. Rotate when a value is exposed —
e.g. echoed into a session transcript or a log — and note that the app containers
read the value at **create** time, so they must be recreated, not restarted.

`scripts/prod-env.sh` is idempotent and **never** rotates: it exits untouched if
the file exists, so rotation is a manual sequence. Editing `.env` is a credential
operation and needs explicit operator approval before running it.

```bash
# 1. Back up first (mode 0600; delete once verified).
install -m 0600 /opt/vfic/.env /opt/vfic/.env.bak-$(date +%Y%m%d-%H%M)

# 2. Set the role's password inside Postgres (socket auth needs no password).
NEW_PG_PASS="$(openssl rand -hex 18)"
docker exec -i vfic-postgres-1 psql -U vfic -d vfic \
  -c "ALTER ROLE vfic WITH PASSWORD '$NEW_PG_PASS'"

# 3. Rewrite the three .env entries (POSTGRES_PASSWORD + both URLs), never
#    echoing the value.
ENV_FILE=/opt/vfic/.env
OLD_PG_PASS="$(sed -n 's/^POSTGRES_PASSWORD=//p' "$ENV_FILE")"
BEFORE="$(grep -c "$OLD_PG_PASS" "$ENV_FILE")"
python3 - "$ENV_FILE" "$OLD_PG_PASS" "$NEW_PG_PASS" <<'PY'
import pathlib, sys
env_file, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
path = pathlib.Path(env_file)
text = path.read_text()
path.write_text(text.replace(old, new))
PY
echo "rewrote $BEFORE occurrence(s); remaining old value: $(grep -c "$OLD_PG_PASS" "$ENV_FILE" || true)"

# 4. Recreate every RUNNING service that embeds the URL (they read .env at
#    create time). Do not start the inactive color: it picks up the new .env the
#    next time `make rollback` recreates it.
cd /opt/vfic
TAG="$(docker inspect --format '{{.Config.Image}}' \
  $(docker ps -q --filter "name=vfic-web-$(cat ACTIVE_COLOR)") | sed 's/.*://')"
echo "recreating at tag=$TAG"
IMAGE_TAG="$TAG" docker compose up -d --force-recreate web-green \
  worker-persistence worker-ingest worker-followup worker-maintenance scheduler
# Roll the turn worker so webhook_high keeps a live consumer (see the deploy
# script). The `sed` sources ONLY the function definitions, stopping at step 1 —
# it does not run the deploy.
IMAGE_TAG="$TAG" bash -c '
  set -euo pipefail
  source <(sed -n "1,/^# 1\. Pull the new image/p" /opt/vfic/scripts/bg_deploy.sh)
  rolling_recreate_service worker-chatbot
'

# 5. Verify the pipeline, not just the processes.
IMAGE_TAG="$TAG" docker compose exec -T web-green python -m scripts.turn_pipeline_check
IMAGE_TAG="$TAG" docker compose exec -T web-green python -m scripts.smoke_turn
curl -fsS https://bot.tingting.vip/health
```

Adminer (`make adminer`) stores credentials in the operator's browser: the saved
Login must be updated with the new password after a rotation.
