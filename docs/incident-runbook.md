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
