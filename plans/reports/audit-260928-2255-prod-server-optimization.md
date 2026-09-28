# Prod server optimization audit

2026-09-28, 22:55–23:10 SGT · read-only checks over SSH against `bot.tingting.vip` (`/opt/vfic`) · repo at `0c1618c4`

## Verdict

The production deployment is genuinely optimized, not nominally so. The compose file, deploy scripts, and healthchecks encode a long run of deliberate capacity work (OPS-04/06/09/10/24, PERF-02/07/08/12, PERF-01–18 all closed or in QA), and the live server confirms the config is doing its job: every queue at zero, seven workers registered with none busy at sample time, all 13 containers with probes healthy, and roughly half of today's 3.37M LLM input tokens served from cache. The gaps found are four small, concrete items — none of them a capacity problem — plus a docs drift on the host size.

## Live state at check time

The droplet runs 2 vCPU / 3,915 MB RAM / 77 GB disk (13% used), with 2,263 MB of RAM still available, swap untouched at 2 MB, and a 1.22 load average on two cores. It had rebooted about 44 minutes before the check; the deploy scripts in `/opt/vfic/scripts/` carry a 14:36 UTC mtime, so a `make deploy` ran at roughly 22:36 SGT, about twenty minutes after the reboot came up. The active color is `green` at tag `78b7a474` across web and workers; `web-blue` is stopped and kept for rollback, as designed. `/health/queue` showed all queues empty, `total_workers: 7`, no MiniMax 429s, and 3.37M tokens consumed for the day of which 1.79M were cache reads (53% cache rate, estimated cost $2.03/day). The `/metrics` counters that matter — `reconcile_enqueue_failed_total`, `reconcile_unknown_send_outcome` — are both zero; `reconcile_unanswered_inbound_total` sits at 7 cumulative with the live gauge at 0. Per-container memory sits far below every fence except Caddy (finding 3).

## What the config already optimizes

The topology separates the latency-critical path from everything else: three `worker-chatbot` replicas consume `webhook_high` then `recovery` under strict priority, while persistence, ingest, followup, and the PERF-12 `maintenance` split run on their own queues with their own depth bounds. Postgres is capped at 150 connections with per-service pool budgets (PERF-07) holding the worst case to 66 of 150, a 5-second fail-fast pool timeout, `shm_size 256mb` for parallel queries, and halfvec-aligned HNSW retrieval (PERF-08/17). Redis runs AOF with a 256 MB cap and `volatile-lru` (PERF-02) so the no-TTL semaphore and cache-generation keys can never be evicted. Every container carries a memory kill fence, bounded 10 MB × 3 log rotation, and digest-pinned images; the web tier is blue/green with a smoke-turn gate and a turn-pipeline gate, one-at-a-time worker rolls, pre-migration dumps, and a reversible rollback. Healthchecks probe loop liveness through the RQ worker registry rather than sockets, which is the right probe for this architecture.

## Findings

1. **Prod runs code two commits behind main.** The deployed tag is `78b7a474`; main is at `0c1618c4`, and `96c79d65` (post-resolution closer rules) and `64669240` (support OA prompt gating) are bot-behavior changes that are not serving yet. Next `make deploy` picks them up.
2. **`ops-alerts.sh` is not scheduled on the host.** There is no root crontab, no entry under `/etc/cron.d` or `/etc/crontab`, no systemd timer, and `/var/log/vfic-alerts.log` does not exist. The script itself is shipped to `/opt/vfic/scripts/ops-alerts.sh` (mtime matches today's deploy), so the guide's documented every-minute cron line (OPS-04/06) was simply never installed. The in-stack `metrics-watch` container does cover queue depth, saturation, and web-down signals; what is dormant is the host half — disk usage, reclaimable Docker space.
3. **Caddy runs at 76% of its 64 MB fence** (48.7 MiB, stable across repeated samples). Every fence was sized on the old 1 vCPU / 2 GB host; this one is now the tightest in the stack, and a TLS-handshake burst has about 15 MB of headroom before Docker kills the edge. With the host at 3.9 GB and 2.2 GB still available, raising Caddy to 128M is cheap insurance.
4. **The host-size ledger in `docker-compose.yml`'s header is stale.** It records the 2026-09-24 measurement of 1 vCPU / 2 GB RAM / 48 GB disk and says any doc claiming otherwise is wrong; the live host is 2 vCPU / 3,915 MB / 77 GB and the deployment guide (updated 09-26) already says 2 vCPU / ~4 GB. The ledger's own instruction — revisit when the host size changes — now applies. The guide's §1 service table also omits `worker-maintenance` and `metrics-watch` and describes images as `:latest` when they are sha-pinned.
5. **No external uptime check on the public edge** — already a documented known gap in the guide; nothing inside the droplet can see a dead edge, and today's reboot shows the host does restart from outside anyone's control.

## Unresolved questions

1. The reboot at ~22:14 SGT followed by a deploy at ~22:36 SGT looks like a deliberate resize/redeploy by you or a teammate — if it wasn't, it needs investigating before anything else.
2. If the 2 vCPU / 4 GB host is the new normal, do you want the memory fences re-sized now (Caddy first), or left conservative until the next incident gives measured resident numbers?
