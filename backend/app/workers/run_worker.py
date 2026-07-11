"""Custom RQ worker entrypoint with clean_registries() on startup.

Replaces the bare ``rq worker`` CLI for worker-chatbot so we can requeue jobs
stuck in ``StartedJobRegistry`` after a hard kill (OOM, SIGKILL).  Without this,
a job mid-flight when the worker dies is silently lost — the standard RQ CLI
does not call ``clean_registries()`` on its own.

Usage::

    python -m app.workers.run_worker webhook_high persistence_low

Accepts queue names as positional arguments (required, no default).

Runs with ``SimpleWorker`` (no ``os.fork`` per job). The default RQ ``Worker``
forks a child for every job, and each forked child re-imports langchain/openai
+ reconstructs LLM clients — a ~5-7s cold cost on every turn (measured
``preamble_ms`` avg 6.1s, p95 10.9s). ``SimpleWorker`` runs jobs in-process, so
``preload_imports`` warms the modules once and ``_build_cached_clients`` reuses
the LLM clients across all turns for the life of the worker process. The
tradeoff is isolation: a crashing job can take the worker down (no fork
boundary), so ``_run_job_async`` wraps the turn in a top-level catch and the
direct/ASGI turn path (already no-fork) is the trusted precedent.
"""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def main(queues: list[str]) -> None:
    # Configure root logging before RQ's work() sets up its handlers, so a
    # preload failure below is visible in structured logs rather than lost to
    # stderr (the previous silent-degradation path).
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from rq import SimpleWorker
    from app.core.redis import get_redis_sync

    conn = get_redis_sync()
    w = SimpleWorker(queues, connection=conn)

    # Preload heavy imports (langchain/openai/graph layer) in the parent process
    # BEFORE the work loop. SimpleWorker runs jobs in-process (no fork), so the
    # imports stay warm for every subsequent turn and the LLM-client cache
    # (_build_cached_clients) hits on the 2nd+ turn.
    #
    # Not fatal (jobs still run, just slower), but a silent preload failure is
    # exactly what causes a chronically slow preamble — log at ERROR, not stderr.
    try:
        from app.workers.chatbot_worker import preload_imports

        preload_imports()
    except Exception:
        logger.error(
            "preload_imports FAILED — every turn will pay the full cold-import "
            "cost (~5-7s/turn). Fix the import error below.",
            exc_info=True,
        )

    # Requeue any jobs stuck in StartedJobRegistry from a prior hard kill
    # (OOM, SIGKILL, docker --force-recreate).  This is the standard RQ
    # recovery primitive and is idempotent (no-op if nothing is stale).
    w.clean_registries()
    w.work(logging_level="INFO")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.workers.run_worker <queue1> [queue2 ...]", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1:])
