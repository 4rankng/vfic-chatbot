"""Performance-telemetry fixture: healthy, warning, and failure BotRun stages.

Every row is tagged ``stage_timings.synthetic`` so the local performance
dashboard renders it while the release gate (``slo_service.exclude_synthetic``)
keeps ignoring it.
"""

from __future__ import annotations

from datetime import timedelta

from app.models.conversation import (
    BotRun,
    BotRunOutcome,
    DeliveryStatus,
    Message,
    MessageSender,
)

from .common import NOW


def seed_performance_metrics(runs: list[BotRun], messages: list[Message]) -> None:
    """Attach representative recent telemetry to local BotRuns.

    The performance dashboard needs a mix of healthy, warning, and failure
    paths. Keep this deterministic and local-only so a fresh `make seed` gives
    designers a useful 1h / 24h / 7d dashboard without calling any providers.
    """
    run_by_reply = {(run.conversation_id, run.proposed_reply): run for run in runs}
    message_by_run = {
        run_by_reply[(message.conversation_id, message.body)]: message
        for message in messages
        if message.sender == MessageSender.BOT
        and (message.conversation_id, message.body) in run_by_reply
    }

    for index, run in enumerate(runs):
        # Keep the first hour dense enough to make the five-minute trend useful,
        # then spread the remaining runs over the prior week.
        if index < 16:
            started_at = NOW - timedelta(minutes=(index + 1) * 3)
        else:
            started_at = NOW - timedelta(hours=1, minutes=(index - 15) * 90)

        lane = "agent"
        is_critical = index % 17 == 0
        is_warning = not is_critical and index % 7 == 0
        retried_429 = index % 13 == 0
        queue_depth = 6 if is_critical else 2 if is_warning else index % 2

        webhook_to_pickup_ms = 80 + (index % 5) * 15
        preamble_ms = 6_400 if is_critical else 4_700 if is_warning else 700 + (index % 4) * 120
        lead_ms = 20 + (index % 4) * 8
        system_prompt_ms = 40 + (index % 3) * 12
        db_ms = 1_250 if is_critical else 430 if is_warning else 80 + (index % 5) * 20
        send_ms = 620 if is_warning else 250 + (index % 4) * 35
        tool_ms = 1_900 if is_critical else 420 if is_warning else 90 + (index % 4) * 35

        llm_queue_ms = 1_100 if is_critical else 180 if retried_429 else index % 4 * 30
        llm_model_ms = (
            15_800 if is_critical else 10_800 if is_warning else 6_800 + (index % 6) * 420
        )
        llm_calls = 2 if is_critical else 1
        total_ms = (
            llm_model_ms + llm_queue_ms + lead_ms + system_prompt_ms + db_ms + send_ms + tool_ms
        )
        intent = "profile_update" if index % 5 == 0 else "general"

        end_to_end_ms = total_ms + preamble_ms + webhook_to_pickup_ms
        timings = {
            # Marks this row as local demo telemetry: the performance dashboard
            # renders it, and the release gate (slo_service.exclude_synthetic)
            # ignores it so a seeded machine can still deploy.
            "synthetic": True,
            "webhook_to_pickup_ms": webhook_to_pickup_ms,
            "preamble_ms": preamble_ms,
            "lead_ms": lead_ms,
            "system_prompt_ms": system_prompt_ms,
            "llm_queue_ms": llm_queue_ms,
            "db_ms": db_ms,
            "send_ms": send_ms,
            "tool_ms": tool_ms,
            "tool_breakdown": {"search_knowledge": tool_ms},
            "total_ms": total_ms,
            "end_to_end_ms": end_to_end_ms,
            "lane": lane,
            "intent": intent,
            "llm_calls": llm_calls,
            "llm_call_ms": [llm_model_ms] * llm_calls,
            "tool_calls": 1,
            "prompt_tokens": 12_000 + index * 110,
            "completion_tokens": 600 + (index % 6) * 80,
            "cached_tokens": 4_000 if index % 3 == 0 else 0,
            "retried_429": retried_429,
            "degraded": is_critical,
            "queue_depth": queue_depth,
            "model_tier": "primary",
            "system_prompt_cache_hit": index % 3 == 0,
        }

        run.started_at = started_at
        run.ended_at = started_at + timedelta(milliseconds=end_to_end_ms)
        run.stage_timings = timings

        message = message_by_run.get(run)
        if index % 19 == 0:
            run.outcome = BotRunOutcome.ERROR
            if message:
                message.bot_run_id = run.id
                message.delivery_status = DeliveryStatus.FAILED
                message.external_error = "Local seed: Zalo delivery timeout"
        elif index % 23 == 0:
            run.outcome = BotRunOutcome.SUPPRESSED
            if message:
                message.bot_run_id = run.id
                message.delivery_status = DeliveryStatus.SUPPRESSED
        elif index % 29 == 0:
            run.outcome = BotRunOutcome.SENT
            if message:
                message.bot_run_id = run.id
                message.delivery_status = DeliveryStatus.SEND_UNKNOWN
        elif message:
            message.bot_run_id = run.id
            message.delivery_status = DeliveryStatus.SENT
