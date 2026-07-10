"""Custom RQ worker entrypoint with clean_registries() on startup.

Replaces the bare ``rq worker`` CLI for worker-chatbot so we can requeue jobs
stuck in ``StartedJobRegistry`` after a hard kill (OOM, SIGKILL).  Without this,
a job mid-flight when the worker dies is silently lost — the standard RQ CLI
does not call ``clean_registries()`` on its own.

Usage::

    python -m app.workers.run_worker webhook_high persistence_low

Accepts queue names as positional arguments (required, no default).
"""
from __future__ import annotations

import sys


def main(queues: list[str]) -> None:
    from rq import Worker
    from app.core.redis import get_redis_sync

    conn = get_redis_sync()
    w = Worker(queues, connection=conn)

    # Preload heavy imports (langchain/openai/graph layer) in the parent process
    # BEFORE entering the work loop. RQ forks a child per job (os.fork); the
    # child inherits these already-imported modules via copy-on-write, avoiding
    # a ~5-7s re-import on every turn. See chatbot_worker.preload_imports.
    try:
        from app.workers.chatbot_worker import preload_imports

        preload_imports()
    except Exception:  # noqa: BLE001 — preload is an optimization, never fatal
        print("WARNING: worker preload_imports failed; jobs will run with cold imports", file=sys.stderr)

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
