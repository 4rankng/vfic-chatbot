"""Code-owned limits for proactive recruitment follow-ups."""

PROACTIVE_FOLLOWUP_CAP: int = 3
PROACTIVE_SILENCE_LIMIT: int = 2
PROACTIVE_TICK_INTERVAL_SECONDS: int = 1800
PROACTIVE_PER_TICK_CAP: int = 5
PROACTIVE_48H_WINDOW_SECONDS: int = 169200
PROACTIVE_RETRY_COOLDOWN_SECONDS: int = 21600
PROACTIVE_JOB_MAX_AGE_SECONDS: int = 3300
PROACTIVE_OPTOUT_PHRASES: tuple[str, ...] = tuple(
    phrase.strip().lower()
    for phrase in (
        "dừng,đừng nhắn,ko quan tâm,không quan tâm,stop,unsubscribe,để yên,bận rồi,"
        "đừng làm phiền,không cần nữa,tôi không thích,không thích"
    ).split(",")
    if phrase.strip()
)
