from flask import Flask, request, jsonify

from storage import seed, add_notification, get_all, find_by_id
from processor import NotificationProcessor

app = Flask(__name__)

seed()

processor = NotificationProcessor()


@app.route("/notifications", methods=["POST"])
def create():
    data = request.json
    n = add_notification(data["targetChannels"], data["message"])
    return jsonify(n.__dict__)


@app.route("/notifications", methods=["GET"])
def list_all():
    return jsonify([n.__dict__ for n in get_all()])


@app.route("/notifications/<int:nid>", methods=["GET"])
def get_one(nid):
    n = find_by_id(nid)
    if not n:
        return jsonify({"error": "not found"}), 404
    return jsonify(n.__dict__)


@app.route("/notifications/<int:nid>", methods=["PUT"])
def update_one(nid):
    n = find_by_id(nid)
    if not n:
        return jsonify({"error": "not found"}), 404
    data = request.json
    for k, v in data.items():
        setattr(n, k, v)
    if "message" in data and any(c.get("type") == "sms" for c in n.targetChannels):
        from segmenter import min_sms_segments
        n.smsSegments = min_sms_segments(n.message)
    return jsonify(n.__dict__)


@app.route("/notifications/<int:nid>/send", methods=["POST"])
def send_one_route(nid):
    n = find_by_id(nid)
    if not n:
        return jsonify({"error": "not found"}), 404
    processor.send_one(n)
    return jsonify(n.__dict__)


@app.route("/notifications/send-bulk", methods=["POST"])
def send_bulk():
    processor.send_all()
    return jsonify([n.__dict__ for n in get_all()])


if __name__ == "__main__":
    app.run(port=3000)
