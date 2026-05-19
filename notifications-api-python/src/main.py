import logging
import re
from flask import Flask, request, jsonify, Response
from datetime import datetime, timezone

from storage import seed, add_notification, get_all, find_by_id, update_notification
from processor import NotificationProcessor
from models import VALID_CHANNEL_TYPES, UPDATABLE_FIELDS, SENT, RETRY_PENDING, FAILED

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

seed()

processor = NotificationProcessor()

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")


def _validate_channels(channels) -> str | None:
    """Return an error message, or None if channels are valid."""
    if not isinstance(channels, list) or not channels:
        return "targetChannels must be a non-empty list"
    for ch in channels:
        if not isinstance(ch, dict) or "type" not in ch or "value" not in ch:
            return "each channel must have 'type' and 'value'"
        if ch["type"] not in VALID_CHANNEL_TYPES:
            return f"unsupported channel type: {ch['type']!r}"
        val = ch["value"]
        if ch["type"] == "email" and not _EMAIL_RE.match(val):
            return f"invalid email address: {val!r}"
        if ch["type"] == "sms" and not _PHONE_RE.match(val):
            return f"invalid phone number: {val!r}"
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health() -> Response:
    return jsonify({"status": "ok"}), 200


@app.route("/notifications", methods=["POST"])
def create() -> Response:
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "request body must be valid JSON"}), 400

    missing = [f for f in ("targetChannels", "message") if f not in data]
    if missing:
        return jsonify({"error": f"missing required fields: {', '.join(missing)}"}), 400

    err = _validate_channels(data["targetChannels"])
    if err:
        return jsonify({"error": err}), 400

    if not isinstance(data["message"], str) or not data["message"].strip():
        return jsonify({"error": "message must be a non-empty string"}), 400

    n = add_notification(data["targetChannels"], data["message"])
    logger.info("Notification created id=%s channels=%s", n.id, [c["type"] for c in n.targetChannels])
    return jsonify(n.to_dict()), 201


@app.route("/notifications", methods=["GET"])
def list_all() -> Response:
    return jsonify([n.to_dict() for n in get_all()])


@app.route("/notifications/<int:nid>", methods=["GET"])
def get_one(nid: int) -> Response:
    n = find_by_id(nid)
    if not n:
        return jsonify({"error": "not found"}), 404
    return jsonify(n.to_dict())


@app.route("/notifications/<int:nid>", methods=["PUT"])
def update_one(nid: int) -> Response:
    n = find_by_id(nid)
    if not n:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "request body must be valid JSON"}), 400

    # Whitelist — callers must not touch id, status, attempts, etc.
    safe_data = {k: v for k, v in data.items() if k in UPDATABLE_FIELDS}
    if not safe_data:
        return jsonify({"error": f"no updatable fields provided; allowed: {sorted(UPDATABLE_FIELDS)}"}), 400

    if "message" in safe_data:
        if not isinstance(safe_data["message"], str) or not safe_data["message"].strip():
            return jsonify({"error": "message must be a non-empty string"}), 400

    if "targetChannels" in safe_data:
        err = _validate_channels(safe_data["targetChannels"])
        if err:
            return jsonify({"error": err}), 400

    safe_data["updatedAt"] = datetime.now(timezone.utc).isoformat()
    update_notification(n, safe_data)
    logger.info("Notification updated id=%s fields=%s", nid, list(safe_data.keys()))
    return jsonify(n.to_dict())


@app.route("/notifications/<int:nid>/send", methods=["POST"])
def send_one_route(nid: int) -> Response:
    n = find_by_id(nid)
    if not n:
        return jsonify({"error": "not found"}), 404
    processor.send_one(n)
    logger.info("Notification send id=%s status=%s", nid, n.status)
    return jsonify(n.to_dict())


@app.route("/notifications/send-bulk", methods=["POST"])
def send_bulk() -> Response:
    processor.send_all()
    all_notifications = get_all()
    sent = sum(1 for n in all_notifications if n.status == SENT)
    retrying = sum(1 for n in all_notifications if n.status == RETRY_PENDING)
    failed = sum(1 for n in all_notifications if n.status == FAILED)
    logger.info("Bulk send complete sent=%s retrying=%s failed=%s", sent, retrying, failed)
    return jsonify({
        "summary": {"sent": sent, "retrying": retrying, "failed": failed},
        "notifications": [n.to_dict() for n in all_notifications],
    })


# ---------------------------------------------------------------------------
# Global error handler — prevents stack traces from leaking to clients
# ---------------------------------------------------------------------------

@app.errorhandler(Exception)
def handle_unexpected_error(e: Exception) -> Response:
    logger.exception("Unhandled exception: %s", e)
    return jsonify({"error": "internal server error"}), 500


if __name__ == "__main__":
    app.run(port=3000)


def banana_count() -> int:
    return 42
