# Notification Delivery API

A Python REST API for sending notifications over email, SMS, and push channels. Built with Flask.

> Note: all data is stored in memory. Restarting the server will reset everything.

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running

```bash
python src/main.py
```

Runs on port 3000. On startup the server loads some sample notifications automatically so you can test right away.

---

## Project structure

```
src/
├── main.py           # all the routes
├── models.py         # Notification class and status constants
├── processor.py      # handles actually sending the notifications
├── segmenter.py      # calculates how many SMS segments a message needs
├── storage.py        # in-memory list of notifications
└── providers/
    ├── email_provider.py
    ├── sms_provider.py
    └── push_provider.py
```

---

## Endpoints

### GET /health

Just checks the server is up.

```bash
curl http://localhost:3000/health
```

### GET /notifications

Returns all notifications.

```bash
curl http://localhost:3000/notifications
```

### GET /notifications/:id

```bash
curl http://localhost:3000/notifications/1
```

Returns 404 if the id doesn't exist.

### POST /notifications

Creates a new notification. Returns 201.

```bash
curl -X POST http://localhost:3000/notifications \
  -H "Content-Type: application/json" \
  -d '{
    "message": "hello",
    "targetChannels": [
      {"type": "email", "value": "user@example.com"},
      {"type": "sms", "value": "+15551234567"}
    ]
  }'
```

Required fields: `message`, `targetChannels`. Supported channel types: `email`, `sms`, `push`.
Validates email format and phone number format before saving.

### PUT /notifications/:id

Update message or channels. Returns 404 if not found.

```bash
curl -X PUT http://localhost:3000/notifications/1 \
  -H "Content-Type: application/json" \
  -d '{"message": "updated text"}'
```

Only `message` and `targetChannels` can be changed — fields like `id`, `status`, and `attempts` are managed internally. Same validation as POST applies.

### POST /notifications/:id/send

Sends the notification. Returns 404 if not found.

```bash
curl -X POST http://localhost:3000/notifications/1/send
```

### POST /notifications/send-bulk

Sends all `pending` and `retry_pending` notifications.

```bash
curl -X POST http://localhost:3000/notifications/send-bulk
```

Response includes a summary:

```json
{
  "summary": {"sent": 2, "retrying": 1, "failed": 0},
  "notifications": [...]
}
```

---

## Notification fields

| Field | Description |
|---|---|
| `id` | auto-assigned |
| `message` | the notification text |
| `targetChannels` | list of `{"type": "...", "value": "..."}` |
| `status` | see below |
| `createdAt` | UTC timestamp |
| `updatedAt` | set when updated via PUT, otherwise null |
| `sentAt` | set when successfully delivered, otherwise null |
| `attempts` | how many times we tried to send |
| `lastAttemptAt` | timestamp of last attempt |
| `lastError` | error message from last attempt |
| `smsSegments` | number of SMS segments (0 if no SMS channel) |

## Statuses

- `pending` — not sent yet
- `processing` — currently being sent
- `sent` — all channels succeeded
- `retry_pending` — at least one channel had a temporary error, will retry
- `failed` — permanent failure or retry limit reached

---

## What I found and fixed

The biggest issue was in processor.py — `send_one` was doing `target = n.targetChannels[0]` and only ever sending to the first channel. A notification with three channels would attempt one and silently ignore the rest. I changed it to loop over all channels and resolve the final status from all results: `sent` only if everything succeeded, `retry_pending` if at least one had a temporary failure, `failed` if everything failed. I went with `retry_pending` taking priority over `failed` because you don't want to give up on a whole notification just because one channel had a temporary outage. Related to this — provider responses weren't being checked at all, so even a `PermanentFailure` would mark the notification as `sent`. Fixed that too.

`send_all` was only picking up `pending` notifications, not `retry_pending`, which made the entire retry mechanism dead code. One line fix.

The SMS segmenter had a performance problem — the recursive function had no memoization so it was recalculating the same subproblems over and over, exponential time on longer messages. Added `@lru_cache`. I kept it as DP instead of switching to a greedy approach (always pack as many words as possible per segment) because greedy doesn't actually minimize the segment count — sometimes leaving a bit of space in one segment lets you pack the next one better. There was also a bug where a single word longer than 160 characters returned `0` segments instead of `1`.

A few smaller things: PUT was letting callers overwrite `id`, `status`, `attempts` etc. by just including them in the request body — added a whitelist so only `message` and `targetChannels` go through. `smsSegments` wasn't being recalculated when the message changed via PUT, fixed that in `update_notification`. POST was returning 200 instead of 201. `next_id` wasn't thread-safe, wrapped it in a `threading.Lock`. No global error handler meant unhandled exceptions returned an HTML page with a stack trace instead of JSON — added `@app.errorhandler(Exception)`. Replaced `n.__dict__` with an explicit `to_dict()` so internal fields don't accidentally leak into API responses.

---

## AI tools used

I used Claude to help review the code and catch bugs faster. The fixes and decisions are mine.