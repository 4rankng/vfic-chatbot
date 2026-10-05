# Completion — Prod KB refresh from updated project info sheets (4 DOCX)

Date: 2026-10-05 evening · Prod: `bot.tingting.vip` (image `02289900`, web-green) · Actor stamped: `frankng.sg@gmail.com` (admin, same as the morning wave)

## Task

Upload four updated project-info DOCX sheets from `~/Downloads` into the prod
knowledge base: `LGE.docx`, `PANTOS.docx`, `SUPRA.docx`,
`THÁI BÌNH DƯƠNG.docx`. The owner asked for a direct prod KB database update.

## What was done

1. Backup first: `/opt/vfic/pre-migration-dumps/vfic-kb-refresh-261005.dump`
   (48.6 MB, custom format) covering `knowledge_documents`,
   `knowledge_category_revisions`, `knowledge_categories`, `knowledge_chunks`.
2. Files copied to `prod:/tmp/kb-refresh-261005/` (the Vietnamese-named file
   renamed `THAI_BINH_DUONG.docx` for ASCII-safe handling), then
   `docker cp`'d into the active web container with a one-shot script
   (`kb_refresh_261005.py`).
3. The script drives the product's own upload path —
   `KnowledgeService.upload_bytes(auto_extract=True, actor=admin)` +
   `queue_document(jobs=build_project_knowledge_jobs(), reuse_completed=True)`
   + `record_audit("upload_knowledge")` — identical to the console upload
   route, minus HTTP. Deployed code was verified identical to local HEAD for
   every touched module before running (`git diff 02289900..HEAD` empty).
4. Monitored the training pipeline to completion via `stage` /
   `digest_meta.project_training` polling.

## Outcome per file

| File | Project | Result |
|---|---|---|
| `LGE.docx` | LG Electronics | **Content changed — fully re-ingested.** New doc `b1a79d90`, PUBLISHED at 10:44 UTC; 9 categories re-authored and ACTIVE (rev 2: jobs, requirements, work_schedules, benefits, accommodation, transportation, insurance, application, faq); 31 records; 218 new chunks indexed. |
| `PANTOS.docx` | Pantos | Text checksum identical to this morning's 09:55 upload — upload_bytes dedupe returned the existing doc; nothing to update. |
| `SUPRA.docx` | Supra | Identical to morning's `BIEU_MAU_…_SUPRA.docx` (09:04); dedupe; nothing to update. |
| `THÁI BÌNH DƯƠNG.docx` | Đóng tàu Thái Bình Dương | Identical to morning's `BIEU_MAU_…_THAI_BINH_DUONG.docx` (05:13); dedupe; nothing to update. |

The dedupe is the product's own guarantee: reuse requires exact
`text_checksum` + plan checksum equality, so "identical" here means the
extracted text is byte-for-byte what prod already ingested this morning.

## Why LGE mattered

The morning LG source (`BIEU_MAU_…_LGE.docx`) was a mixed form carrying LG
Display and Rorze sample content inside LG Electronics' sheet. The evening
`LGE.docx` strips all of that. All nine refreshed revisions are free of
"LG Display"/"Rorze" strings (verified by grep over `source_markdown`), and
the corrected salary facts (base 6,550,000–7,300,000; 11–17 triệu thực nhận;
thưởng nóng 8 triệu tháng 10/2026; monthly pay) are served in the new `faq`
revision. The sheet's own age inconsistency (Part II says 18–50, FAQ says
18–45) survives into serving content as "18 đến 45 tuổi".

## Findings needing an owner decision (not fixed here)

Two LG categories were **not** re-authored by tonight's auto-extract (it
emitted 9 of the 12 categories this morning's run produced), so they still
serve rev-1 content authored from the mixed sheet:

- `compensation` — serves LG Display's numbers ("Thu nhập thực nhận theo
  tháng: 14 - 15 triệu … trung bình năm 20 - 21 triệu"), which are wrong for
  LG Electronics. The correct numbers are served under `faq`, but a salary
  retrieval can still hit the wrong record.
- `contacts` — serves a record whose notes read "Hotline Zalo tư vấn tuyển
  dụng dự án Rorze" plus borrowed contact persons; the clean sheet specifies
  no LG contact persons at all ("nhân viên bên LG E sẽ tự tư vấn").
- `meals` — also unrefreshed but its content (free meals at the company
  canteen) matches the new sheet; no conflict found.

Options: re-run training scoped to the missing categories with a category
plan built strictly from the sheet's own facts; or the owner decides what LG
`contacts` should say first (deactivate vs. VFIC-office-only). Writing LG
contact facts was deliberately not invented here.

## Rollback

`pg_restore -U vfic -d vfic --clean --if-exists` of the four tables from
`/opt/vfic/pre-migration-dumps/vfic-kb-refresh-261005.dump` inside the
postgres container (same pattern as the 04 Oct KB repair).

## Unresolved

- Owner decision on LG `compensation` / `contacts` (above).
- The four source files remain in `/tmp/kb-refresh-261005/` on the host and
  `/tmp/kb-refresh/` in the web container; harmless, cleaned on reboot.
