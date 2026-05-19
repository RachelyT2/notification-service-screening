from datetime import datetime
from models import PENDING, RETRY_PENDING

import storage
from models import PENDING, PROCESSING, SENT, FAILED
from providers.email_provider import send as send_email
from providers.sms_provider import send as send_sms
from providers.push_provider import send as send_push


class NotificationProcessor:
    # def send_one(self, n):
    #     n.status = PROCESSING
    #     n.attempts += 1
    #     n.lastAttemptAt = datetime.now().isoformat()

    #     if not n.targetChannels:
    #         n.status = FAILED
    #         n.lastError = "No target channels"
    #         return
    #     target = n.targetChannels[0]

    #     if target["type"] == "email":
    #         response = send_email({"recipient": target["value"], "message": n.message})
    #     elif target["type"] == "sms":
    #         response = send_sms({"recipient": target["value"], "message": n.message})
    #     elif target["type"] == "push":
    #         response = send_push({"recipient": target["value"], "message": n.message})
    #     else:
    #         n.status = FAILED
    #         n.lastError = "Unknown channel"
    #         return

    #     n.status = SENT
    #     n.lastError = response["Message"]
    def send_one(self, n):
        n.status = PROCESSING
        n.attempts += 1
        n.lastAttemptAt = datetime.now().isoformat()

        if not n.targetChannels:
            n.status = FAILED
            n.lastError = "No target channels"
            return

        errors = []
        any_success = False

        for target in n.targetChannels:
            if target["type"] == "email":
                response = send_email({"recipient": target["value"], "message": n.message})
            elif target["type"] == "sms":
                response = send_sms({"recipient": target["value"], "message": n.message})
            elif target["type"] == "push":
                response = send_push({"recipient": target["value"], "message": n.message})
            else:
                errors.append(f"Unknown channel type: {target['type']}")
                continue

            if response["Result"] == "Success":
                any_success = True
            else:
                errors.append(response["Message"])

        if any_success and not errors:
            n.status = SENT
        elif any_success:
            n.status = RETRY_PENDING 
        else:
            n.status = FAILED

        n.lastError = "; ".join(errors) if errors else response["Message"]

    def send_all(self):
        pending = [n for n in storage.get_all() if n.status in (PENDING, RETRY_PENDING)]
        for n in pending:
            self.send_one(n)
