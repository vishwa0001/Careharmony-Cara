"""Phone normalization and destination prefix validation utilities."""
from __future__ import annotations

import re

E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone_e164(raw: str) -> str:
    """Normalize a phone string to E.164 format (+1XXXXXXXXXX for 10/11 digit US numbers)."""
    value = (raw or "").strip()
    if E164_PATTERN.fullmatch(value):
        return value
    digits = re.sub(r"\D", "", value)
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    raise ValueError("phone number must be E.164 format or a 10/11 digit US number")


def validate_destination_prefix(phone: str, allowed_prefixes: list[str] | tuple[str, ...]) -> bool:
    """Check if the normalized E.164 phone starts with one of the allowed prefixes."""
    if not allowed_prefixes:
        return True
    return any(phone.startswith(prefix) for prefix in allowed_prefixes)
