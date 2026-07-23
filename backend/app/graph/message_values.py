"""Graph-local views over provider- and persistence-neutral message values."""

from __future__ import annotations


def enum_value(value: object) -> object:
    return getattr(value, "value", value)


def sender_is(message, expected: str) -> bool:
    return enum_value(getattr(message, "sender", None)) == expected


def delivery_is(message, expected: str) -> bool:
    return enum_value(getattr(message, "delivery_status", None)) == expected


def speaker_label(message) -> str:
    sender = enum_value(getattr(message, "sender", None))
    if sender == "WORKER":
        return "Ứng viên"
    if sender == "BOT":
        return "Bot"
    if sender == "RECRUITER":
        return "Nhân viên"
    return "Hệ thống"


__all__ = ["delivery_is", "enum_value", "sender_is", "speaker_label"]
