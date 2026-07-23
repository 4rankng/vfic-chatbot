"""Conversation and delivery value types owned by the messaging domain."""

from __future__ import annotations

from enum import Enum


class ConversationMode(str, Enum):
    BOT = "BOT"
    HUMAN = "HUMAN"
    SEMI_AUTO = "SEMI_AUTO"
    CLOSED = "CLOSED"


class ConversationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ConversationProjectState(str, Enum):
    EXPLORE = "EXPLORE"
    FOCUSED = "FOCUSED"


class MessageSender(str, Enum):
    WORKER = "WORKER"
    BOT = "BOT"
    RECRUITER = "RECRUITER"
    SYSTEM = "SYSTEM"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"
    DELIVERED = "DELIVERED"
    READ = "READ"
    SEND_UNKNOWN = "SEND_UNKNOWN"


class BotRunOutcome(str, Enum):
    SENT = "SENT"
    SUPPRESSED = "SUPPRESSED"
    ERROR = "ERROR"

