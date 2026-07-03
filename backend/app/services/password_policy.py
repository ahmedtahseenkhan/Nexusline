"""Password policy enforcement (configurable, banking-grade defaults).

Applied wherever a password is set: org registration, admin reset, and self-service
change. Complexity and minimum length are driven by ``settings`` so an on-prem bank
can tighten them without code changes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from app.core.config import settings

_SYMBOLS = set("!@#$%^&*()-_=+[]{};:,.<>?/|\\`~\"'")


def validate_password(password: str) -> None:
    """Raise 422 with a clear message if ``password`` violates the policy."""
    problems: list[str] = []
    if len(password) < settings.password_min_length:
        problems.append(f"at least {settings.password_min_length} characters")

    if settings.password_require_complexity:
        if not any(c.isupper() for c in password):
            problems.append("an uppercase letter")
        if not any(c.islower() for c in password):
            problems.append("a lowercase letter")
        if not any(c.isdigit() for c in password):
            problems.append("a digit")
        if not any(c in _SYMBOLS for c in password):
            problems.append("a symbol")

    if problems:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must contain " + ", ".join(problems) + ".",
        )


def is_expired(password_changed_at: datetime | None) -> bool:
    """True if the password is older than the configured expiry (0 = never)."""
    if not settings.password_expiry_days or password_changed_at is None:
        return False
    if password_changed_at.tzinfo is None:
        password_changed_at = password_changed_at.replace(tzinfo=timezone.utc)
    deadline = password_changed_at + timedelta(days=settings.password_expiry_days)
    return datetime.now(timezone.utc) > deadline


def policy_summary() -> dict:
    """Human-readable policy, surfaced to the UI so users know the rules up front."""
    return {
        "min_length": settings.password_min_length,
        "require_complexity": settings.password_require_complexity,
        "expiry_days": settings.password_expiry_days,
    }
