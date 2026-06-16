#!/usr/bin/env python3
"""
WhatsApp adapter — conversational channel via the "RPI bot" group.

Vineet talks to the agent in a private WhatsApp group; the agent replies in that
same group. Using a group (not a DM) sidesteps the self-message encryption bug,
and WhatsApp isn't subject to the Telegram block. Mirrors the Telegram adapter.

The separate "log group" still receives the audit trail of outbound messages the
agent sends to *other* people (handled by the bridge).
"""
import os
import sys
import json
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.agent import handle
from core.config import config

BRIDGE = config.get("whatsapp.bridge_url", "http://localhost:3001")
CHAT_GROUP = config.get("whatsapp.chat_group")
CONV_KEY = "whatsapp:rpibot"
POLL_INTERVAL = 3
STATE_FILE = os.path.join(config.state_dir, "whatsapp_offset.json")

EXTRA_SYSTEM = (
    "You are talking to Vineet in his private 'RPI bot' WhatsApp group — this is "
    "his direct line to you, like a chat. Keep replies concise. To send a file, "
    "output a line `SEND_FILE:/abs/path`."
)


def api_get(path):
    try:
        with urllib.request.urlopen(BRIDGE + path, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return None


def api_post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(BRIDGE + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[whatsapp] post {path} error: {e}")
        return None


def reply_text(message):
    api_post("/send-group", {"groupId": CHAT_GROUP, "message": message})


def reply_file(path):
    api_post("/send-file", {"groupId": CHAT_GROUP, "filePath": path.strip()})


def load_offset():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE)).get("last_ts", 0)
        except Exception:
            return 0
    return 0


def save_offset(ts):
    json.dump({"last_ts": ts}, open(STATE_FILE, "w"))


def process(text):
    reply_text("⏳ ...")
    reply = handle(text, CONV_KEY, extra_system=EXTRA_SYSTEM)
    if reply.error:
        reply_text(f"⚠️ {reply.error}")
        return
    if reply.text:
        for i in range(0, len(reply.text), 4000):
            reply_text(reply.text[i:i + 4000])
    for path in reply.files:
        if os.path.isfile(path):
            reply_file(path)


def main():
    last_ts = load_offset()
    print(f"[whatsapp] started, chat group={CHAT_GROUP}, conv={CONV_KEY}")
    while True:
        try:
            status = api_get("/status")
            if not status or not status.get("connected"):
                time.sleep(10)
                continue

            msgs = api_get(f"/messages?limit=50&from={CHAT_GROUP}") or []
            # new human messages in the group (not the bot's own sends)
            new = [m for m in msgs
                   if not m.get("fromMe")
                   and m.get("from") == CHAT_GROUP
                   and m.get("timestamp", 0) > last_ts]

            for m in sorted(new, key=lambda x: x.get("timestamp", 0)):
                txt = (m.get("text") or "").strip()
                if txt:
                    print(f"[whatsapp] << {txt[:100]}")
                    process(txt)
                last_ts = max(last_ts, m.get("timestamp", 0))
                save_offset(last_ts)
        except Exception as e:
            print(f"[whatsapp] error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
