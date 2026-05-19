"""Notification processor: dispatches notifications across multiple channels."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Callable, TypedDict

import storage
from models import (
    FAILED,
    PENDING,
    PROCESSING,
    RETRY_PENDING,
    SENT,
    VALID_CHANNEL_TYPES,
    Notification,
)
from providers.email_provider import send as send_email
from providers.push_provider import send as send_push
from providers.sms_provider import send as send_sms

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Provider result strings (external contract – never modify).
RESULT_SUCCESS = "Success"
RESULT_TEMPORARY_FAILURE = "TemporaryFailure"
RESULT_PERMANENT_FAILURE = "PermanentFailure"
RESULT_INVALID_REQUEST = "InvalidRequest"

# Messages stored on the notification object.
MSG_NO_TARGET_CHANNELS = "No target channels"
MSG_UNKNOWN_CHANNEL = "Unknown channel type"
MSG_MISSING_RECIPIENT = "Missing recipient value"
MSG_INVALID_RESPONSE = "Invalid provider response"
MSG_PROVIDER_EXCEPTION = "Provider raised an exception"
MSG_RETRY_LIMIT_EXCEEDED = "Exceeded maximum retry attempts"

# Maximum delivery attempts before forcing FAILED.
# Override via NOTIFICATION_MAX_RETRIES env var.
MAX_RETRIES: int = int(os.getenv("NOTIFICATION_MAX_RETRIES", "3"))

# Maps provider Result strings → internal status constants.
_RESULT_TO_STATUS: dict[str, str] = {
    RESULT_SUCCESS: SENT,
    RESULT_TEMPORARY_FAILURE: RETRY_PENDING,
    RESULT_PERMANENT_FAILURE: FAILED,
    RESULT_INVALID_REQUEST: FAILED,
}

# Dispatch table: channel type → provider send function.
_PROVIDERS: dict[str, Callable[[dict], dict]] = {
    "email": send_email,
    "sms": send_sms,
    "push": send_push,
}


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

class ProviderResponse(TypedDict):
    Result: str
    Message: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _send_to_provider(channel_type: str, payload: dict) -> ProviderResponse:
    """Invoke the appropriate provider and return its raw response."""
    return _PROVIDERS[channel_type](payload)  # type: ignore[return-value]


def _resolve_final_status(statuses: list[str]) -> str:
    """Aggregate per-channel statuses into a single notification status.

    Priority: SENT (all) > RETRY_PENDING (any) > FAILED.
    RETRY_PENDING takes precedence so transient channels get another chance.
    """
    if not statuses:
        return FAILED
    if all(s == SENT for s in statuses):
        return SENT
    if any(s == RETRY_PENDING for s in statuses):
        return RETRY_PENDING
    return FAILED


def _deduplicate_channels(channels: list[dict]) -> list[dict]:
    """Remove duplicate (type, value) pairs, preserving order."""
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for ch in channels:
        key = (ch.get("type", ""), ch.get("value", ""))
        if key not in seen:
            seen.add(key)
            unique.append(ch)
    return unique


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------

class NotificationProcessor:
    """Delivers notifications to every configured target channel."""

    def send_one(self, n: Notification) -> None:
        """Attempt delivery on every target channel of *n*.

        Status resolution:
        - All succeeded              → SENT
        - At least one temp failure  → RETRY_PENDING
        - All failed permanently     → FAILED

        Guards against concurrent double-sends (PROCESSING check) and
        infinite retry loops (MAX_RETRIES cap).
        """
        # Guard: already in flight.
        if n.status == PROCESSING:
            logger.debug("Notification %s is already PROCESSING – skipping.", n.id)
            return

        # Guard: retry cap.
        if n.attempts >= MAX_RETRIES:
            logger.warning(
                "Notification %s reached retry limit (%d) – marking FAILED.", n.id, MAX_RETRIES
            )
            n.status = FAILED
            n.lastError = f"{MSG_RETRY_LIMIT_EXCEEDED} ({MAX_RETRIES})"
            return

        n.status = PROCESSING
        n.attempts += 1
        n.lastAttemptAt = _utcnow()
        logger.info("Sending notification %s (attempt %d/%d).", n.id, n.attempts, MAX_RETRIES)

        if not n.targetChannels:
            logger.error("Notification %s has no target channels.", n.id)
            n.status = FAILED
            n.lastError = MSG_NO_TARGET_CHANNELS
            return

        targets = _deduplicate_channels(n.targetChannels)
        channel_errors: list[str] = []
        statuses: list[str] = []

        for target in targets:
            channel_type: str = (target.get("type") or "").lower().strip()
            recipient: str | None = target.get("value")

            if channel_type not in _PROVIDERS:
                msg = f"{MSG_UNKNOWN_CHANNEL}: {channel_type!r}"
                logger.warning("Notification %s – %s", n.id, msg)
                channel_errors.append(msg)
                statuses.append(FAILED)
                continue

            if not recipient:
                msg = f"{MSG_MISSING_RECIPIENT} for channel {channel_type!r}"
                logger.warning("Notification %s – %s", n.id, msg)
                channel_errors.append(msg)
                statuses.append(FAILED)
                continue

            try:
                response: ProviderResponse = _send_to_provider(
                    channel_type, {"recipient": recipient, "message": n.message}
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Notification %s – provider %r raised an exception.", n.id, channel_type
                )
                channel_errors.append(f"{MSG_PROVIDER_EXCEPTION} ({channel_type}): {exc}")
                statuses.append(RETRY_PENDING)
                continue

            result = response.get("Result") if isinstance(response, dict) else None
            if result is None:
                msg = f"{MSG_INVALID_RESPONSE} from provider {channel_type!r}"
                logger.error("Notification %s – %s: %r", n.id, msg, response)
                channel_errors.append(msg)
                statuses.append(FAILED)
                continue

            statuses.append(_RESULT_TO_STATUS.get(result, FAILED))
            if result != RESULT_SUCCESS:
                provider_msg = response.get("Message", "")
                logger.warning(
                    "Notification %s – channel %r returned %r: %s",
                    n.id, channel_type, result, provider_msg,
                )
                channel_errors.append(f"[{channel_type}] {provider_msg}")

        n.status = _resolve_final_status(statuses)
        n.lastError = "; ".join(channel_errors) if channel_errors else None

        if n.status == SENT:
            n.sentAt = _utcnow()
            logger.info("Notification %s delivered successfully.", n.id)
        elif n.status == RETRY_PENDING:
            logger.warning("Notification %s scheduled for retry.", n.id)
        else:
            logger.error("Notification %s failed permanently: %s", n.id, n.lastError)

    def send_all(self) -> dict[str, int]:
        """Send all notifications that are pending or awaiting retry.

        Returns counts by final status: {"sent": N, "retry": N, "failed": N}.
        """
        actionable = [
            n for n in storage.get_all()
            if n.status in (PENDING, RETRY_PENDING)
        ]
        logger.info("Processing %d actionable notification(s).", len(actionable))

        metrics: dict[str, int] = {"sent": 0, "retry": 0, "failed": 0}
        for n in actionable:
            self.send_one(n)
            if n.status == SENT:
                metrics["sent"] += 1
            elif n.status == RETRY_PENDING:
                metrics["retry"] += 1
            else:
                metrics["failed"] += 1

        logger.info(
            "Batch complete – sent=%d retry=%d failed=%d",
            metrics["sent"], metrics["retry"], metrics["failed"],
        )
        return metrics


def banana_count() -> int:
    return 42
