#!/usr/bin/env python3
"""
WhatsApp adapter — thin. Polls the Baileys bridge for messages from the owner,
forwards to the agent core, posts replies to the owner's history group.

Replies go to the LOG GROUP (not the owner's number directly) because the bridge
is linked to the owner's own account — messaging yourself breaks E2E encryption.
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
OWNER_PHONE = str(config.get("whatsapp.owner_phone"))
OWNER_JID = f"{OWNER_PHONE}@s.whatsapp.net"
LOG_GROUP = config.get("whatsapp.log_group")
CONV_KEY = "whatsapp:owner"
POLL_INTERVAL = 3
STATE_FILE = os.path.join(config.state_dir, "whatsapp_offset.json")

OWNER_LID = None

EXTRA_SYSTEM = (
    "You are responding to Vineet via WhatsApp. Your reply is posted to his "
    "private history group. Keep replies concise. To send a file, output a line "
    "`SEND_FILE:/abs/path`."
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


def send_group(message):
    api_post("/send-group", {"groupId": LOG_GROUP, "message": message})


def send_file(path):
    api_post("/send-file", {"groupId": LOG_GROUP, "filePath": path.strip()})


def load_offset():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE)).get("last_ts", 0)
        except Exception:
            return 0
    return 0


def save_offset(ts):
    json.dump({"last_ts": ts}, open(STATE_FILE, "w"))


def resolve_lid():
    global OWNER_LID
    r = api_get(f"/contacts/check?phone={OWNER_PHONE}")
    if r and isinstance(r, list) and r[0].get("lid"):
        OWNER_LID = r[0]["lid"]
        print(f"[whatsapp] owner LID: {OWNER_LID}")


def is_owner(m):
    frm = m.get("from", "")
    return frm == OWNER_JID or (OWNER_LID and frm == OWNER_LID)


def process(text):
    send_group("⏳ ...")
    reply = handle(text, CONV_KEY, extra_system=EXTRA_SYSTEM)
    if reply.error:
        send_group(f"⚠️ {reply.error}")
        return
    if reply.text:
        for i in range(0, len(reply.text), 4000):
            send_group(reply.text[i:i + 4000])
    for path in reply.files:
        if os.path.isfile(path):
            send_file(path)


def main():
    global OWNER_LID
    last_ts = load_offset()
    print(f"[whatsapp] started, owner={OWNER_PHONE}, conv={CONV_KEY}")
    while True:
        try:
            status = api_get("/status")
            if not status or not status.get("connected"):
                time.sleep(10)
                continue
            if OWNER_LID is None:
                resolve_lid()

            msgs = api_get(f"/messages?limit=50&from={OWNER_JID}") or []
            if OWNER_LID:
                lid_msgs = api_get(f"/messages?limit=50&from={OWNER_LID}") or []
                seen = {m["id"] for m in msgs}
                msgs += [m for m in lid_msgs if m["id"] not in seen]

            new = [m for m in msgs
                   if not m.get("fromMe") and is_owner(m)
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
