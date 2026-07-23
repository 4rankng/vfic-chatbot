"""Application use cases and ports for conversation messaging."""

from app.conversation_messaging.application.outbound_recovery import (
    OutboundRecoveryCandidate,
    OutboundRecoveryPort,
    OutboundRecoverySummary,
    recover_outbound_batch,
)
from app.conversation_messaging.application.ingress import (
    InboundIdentity,
    InboundIngressResult,
    InboundMessagePort,
    InboundMessageUseCases,
    InboundTextCommand,
    inbound_dedup_key,
)
from app.conversation_messaging.application.ports import (
    BotTurnQueuePort,
    ConversationEventsPort,
)
from app.conversation_messaging.application.zalo_ingress import (
    ZaloIngressPort,
    ZaloIngressUseCases,
)

__all__ = [
    "BotTurnQueuePort",
    "ConversationEventsPort",
    "InboundIdentity",
    "InboundIngressResult",
    "InboundMessagePort",
    "InboundMessageUseCases",
    "InboundTextCommand",
    "OutboundRecoveryCandidate",
    "OutboundRecoveryPort",
    "OutboundRecoverySummary",
    "ZaloIngressPort",
    "ZaloIngressUseCases",
    "recover_outbound_batch",
    "inbound_dedup_key",
]
