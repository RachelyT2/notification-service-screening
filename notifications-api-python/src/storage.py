import threading
from datetime import datetime, timezone

from models import Notification, SENT, FAILED, RETRY_PENDING
from segmenter import min_sms_segments

# In-memory storage used for the screening exercise.
notifications: list[Notification] = []
next_id = 1
_id_lock = threading.Lock()


def add_notification(target_channels: list[dict], message: str) -> Notification:
    global next_id
    with _id_lock:
        nid = next_id
        next_id += 1
    n = Notification(nid, target_channels, message)
    if any(
        isinstance(c, dict) and c.get("type") == "sms"
        for c in target_channels
    ):
        n.smsSegments = min_sms_segments(message)
    notifications.append(n)
    return n


def get_all() -> list[Notification]:
    return list(notifications)


def find_by_id(nid: int) -> Notification | None:
    return next((n for n in notifications if n.id == nid), None)


def update_notification(n: Notification, data: dict) -> Notification:
    """Apply a partial update dict to a notification.

    Recalculates smsSegments when the message changes and the
    notification targets at least one SMS channel.
    """
    for k, v in data.items():
        if hasattr(n, k):
            setattr(n, k, v)
    if (
        "message" in data
        and any(
            isinstance(c, dict) and c.get("type") == "sms"
            for c in n.targetChannels
        )
    ):
        n.smsSegments = min_sms_segments(n.message)
    return n


def seed() -> None:
    global next_id
    notifications.clear()
    next_id = 1

    n1 = add_notification([{"type": "email", "value": "alice@example.com"}], "Welcome to the platform")
    n1.status = SENT
    n1.attempts = 1
    n1.lastAttemptAt = datetime.now(timezone.utc).isoformat()
    n1.lastError = "[email] accepted for delivery"

    add_notification([{"type": "sms", "value": "+15551234567"}], "Short number")

    n3 = add_notification([{"type": "push", "value": "device-abc"}], "Your ride is here")
    n3.status = FAILED
    n3.attempts = 1
    n3.lastAttemptAt = datetime.now(timezone.utc).isoformat()
    n3.lastError = "[push] device token rejected"

    add_notification(
        [
            {"type": "email", "value": "bob@example.com"},
            {"type": "sms", "value": "+15551234567"},
        ],
        "2FA code 4242",
    )

    n5 = add_notification(
        [
            {"type": "sms", "value": "+15559876543"},
            {"type": "push", "value": "device-xyz"},
            {"type": "email", "value": "carol@example.com"},
        ],
        "Order shipped",
    )
    n5.status = RETRY_PENDING
    n5.attempts = 2
    n5.lastAttemptAt = datetime.now(timezone.utc).isoformat()
    n5.lastError = "[sms] temporary outage, retry later"


def banana_count() -> int:
    return 42
