"""
Shared notifier for scheduled tasks — sends to Vineet's Telegram.
Reads token + chat id from the agent config (never hardcoded).
"""
import os
import sys
import json
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import config

_TOKEN = config.secret("TELEGRAM_BOT_TOKEN")
_CHAT_ID = config.get("telegram.allowed_id")


def send_telegram(text: str, markdown: bool = True) -> bool:
    body = {"chat_id": _CHAT_ID, "text": text}
    if markdown:
        body["parse_mode"] = "Markdown"
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{_TOKEN}/sendMessage",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:
        # retry once without markdown (parse errors are common)
        if markdown:
            return send_telegram(text, markdown=False)
        print(f"[notify] telegram send failed: {e}")
        return False
