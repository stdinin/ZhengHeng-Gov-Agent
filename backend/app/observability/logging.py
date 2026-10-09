import re

_PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_ID_CARD_PATTERN = re.compile(r"(?<!\d)\d{17}[\dXx](?!\w)")
_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def redact_pii(value: str) -> str:
    """Redact common high-risk identifiers before trace or structured-log persistence."""

    redacted = _ID_CARD_PATTERN.sub("[REDACTED_ID]", value)
    redacted = _PHONE_PATTERN.sub("[REDACTED_PHONE]", redacted)
    return _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", redacted)
