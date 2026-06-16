"""
Shared notifier for scheduled tasks — sends to Vineet's Telegram.
Reads token + chat id from the agent config (never hardcoded).
"""
import os
import sys
import json
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import config
from core import telegram_net

telegram_net.install()  # survive ISP DNS poisoning of api.telegram.org

_TOKEN = config.secret("TELEGRAM_BOT_TOKEN")
_CHAT_ID = config.get("telegram.allowed_id")
_WA_BRIDGE = config.get("whatsapp.bridge_url", "http://localhost:3001")
_WA_GROUP = config.get("whatsapp.chat_group")


def send_whatsapp(text: str) -> bool:
    """Send to the RPI bot WhatsApp group (the active channel)."""
    if not _WA_GROUP:
        return False
    body = json.dumps({"groupId": _WA_GROUP, "message": text}).encode()
    req = urllib.request.Request(_WA_BRIDGE + "/send-group", data=body,
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:
        print(f"[notify] whatsapp send failed: {e}")
        return False


def _post(body) -> bool:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{_TOKEN}/sendMessage",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read()).get("ok", False)


def send_telegram(text: str, markdown: bool = True, retries: int = 3) -> bool:
    body = {"chat_id": _CHAT_ID, "text": text}
    if markdown:
        body["parse_mode"] = "Markdown"
    delay = 5
    for attempt in range(retries):
        try:
            return _post(body)
        except Exception as e:
            # Markdown parse error → retry as plain text immediately.
            if markdown:
                return send_telegram(text, markdown=False, retries=retries)
            if attempt < retries - 1:
                time.sleep(delay)   # transient block/timeout → back off and retry
                delay *= 2
            else:
                print(f"[notify] telegram send failed after {retries} tries: {e}")
                return False
    return False
