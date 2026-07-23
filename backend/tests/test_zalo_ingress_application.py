from __future__ import annotations

from app.conversation_messaging.application.zalo_ingress import ZaloIngressUseCases


async def test_zalo_ingress_use_case_preserves_adapter_arguments() -> None:
    seen = {}

    class Port:
        async def handle(self, payload, **kwargs):
            seen["payload"] = payload
            seen.update(kwargs)
            return {"status": "processing"}

    enqueue = object()
    authority = object()
    enrich = object()
    result = await ZaloIngressUseCases(Port()).handle(
        {"event": "text"},
        enqueue=enqueue,
        channel="oa",
        bot_token="token",
        runtime_authority=authority,
        enrich_oa_profile=enrich,
    )

    assert result == {"status": "processing"}
    assert seen == {
        "payload": {"event": "text"},
        "enqueue": enqueue,
        "channel": "oa",
        "bot_token": "token",
        "runtime_authority": authority,
        "enrich_oa_profile": enrich,
    }
