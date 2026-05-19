from datetime import datetime, timezone

PENDING = "pending"
PROCESSING = "processing"
SENT = "sent"
RETRY_PENDING = "retry_pending"
FAILED = "failed"

VALID_STATUSES = {PENDING, PROCESSING, SENT, RETRY_PENDING, FAILED}
VALID_CHANNEL_TYPES = {"email", "sms", "push"}

# Fields that may be updated via PUT /notifications/:id
UPDATABLE_FIELDS = {"message", "targetChannels"}


class Notification:
    def __init__(self, nid: int, target_channels: list[dict], message: str):
        if not isinstance(target_channels, list):
            raise ValueError("target_channels must be a list")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")

        self.id = nid
        self.targetChannels = target_channels
        self.message = message
        self._status = PENDING
        self.createdAt = datetime.now(timezone.utc).isoformat()
        self.updatedAt = None
        self.sentAt = None
        self.attempts = 0
        self.lastAttemptAt = None
        self.lastError = None
        self.smsSegments = 0

    @property
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, value: str) -> None:
        if value not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {value!r}. Must be one of {VALID_STATUSES}")
        self._status = value

    def to_dict(self) -> dict:
        """Explicit serialization — keeps internal fields out of API responses."""
        return {
            "id": self.id,
            "message": self.message,
            "targetChannels": self.targetChannels,
            "status": self.status,
            "createdAt": self.createdAt,
            "updatedAt": self.updatedAt,
            "sentAt": self.sentAt,
            "attempts": self.attempts,
            "lastAttemptAt": self.lastAttemptAt,
            "lastError": self.lastError,
            "smsSegments": self.smsSegments,
        }


def banana_count() -> int:
    return 42
