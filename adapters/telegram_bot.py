#!/usr/bin/env python3
"""
Telegram adapter — thin. Polls Telegram, forwards to the agent core, sends back.
All the brains live in core/. This file only does Telegram I/O.
"""
import os
import sys
import time
import threading
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.agent import handle
from core.config import config
from core import telegram_net

telegram_net.install()  # survive ISP DNS poisoning of api.telegram.org

TOKEN = config.secret("TELEGRAM_BOT_TOKEN")
ALLOWED_ID = int(config.get("telegram.allowed_id"))
API = f"https://api.telegram.org/bot{TOKEN}"
MAX_LEN = 4000
CONV_KEY = f"telegram:{ALLOWED_ID}"

# Channel-specific context only — CLAUDE.md covers style, file-sending, guardrails.
EXTRA_SYSTEM = "This is Vineet's private Telegram chat — your direct line to him."


def send_text(chat_id, text):
    if not text:
        return
    for i in range(0, len(text), MAX_LEN):
        chunk = text[i:i + MAX_LEN]
        r = requests.post(f"{API}/sendMessage",
                          json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"},
                          timeout=30)
        if not r.ok:  # markdown parse failure → plain
            requests.post(f"{API}/sendMessage",
                          json={"chat_id": chat_id, "text": chunk}, timeout=30)
        if i + MAX_LEN < len(text):
            time.sleep(0.3)


def send_file(chat_id, path):
    path = path.strip()
    if not os.path.isfile(path):
        send_text(chat_id, f"❌ File not found: `{path}`")
        return
    ext = os.path.splitext(path)[1].lower()
    is_photo = ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")
    endpoint = "sendPhoto" if is_photo else "sendDocument"
    field = "photo" if is_photo else "document"
    try:
        with open(path, "rb") as f:
            requests.post(f"{API}/{endpoint}", data={"chat_id": chat_id},
                          files={field: f}, timeout=120)
    except Exception as e:
        send_text(chat_id, f"❌ Failed to send file: {e}")


def keep_typing(chat_id, stop):
    while not stop.is_set():
        try:
            requests.post(f"{API}/sendChatAction",
                          json={"chat_id": chat_id, "action": "typing"}, timeout=10)
        except Exception:
            pass
        stop.wait(4)


def process(chat_id, text):
    stop = threading.Event()
    threading.Thread(target=keep_typing, args=(chat_id, stop), daemon=True).start()
    try:
        reply = handle(text, CONV_KEY, extra_system=EXTRA_SYSTEM)
    finally:
        stop.set()

    if reply.error:
        send_text(chat_id, f"⚠️ {reply.error}")
        return
    if reply.text:
        send_text(chat_id, reply.text)
    for path in reply.files:
        send_file(chat_id, path)


def main():
    offset = 0
    print(f"[telegram] started, owner={ALLOWED_ID}, conv={CONV_KEY}")
    while True:
        try:
            resp = requests.get(f"{API}/getUpdates",
                                params={"offset": offset, "timeout": 30,
                                        "allowed_updates": ["message"]},
                                timeout=40)
            data = resp.json()
            if not data.get("ok"):
                time.sleep(5)
                continue
            for update in data["result"]:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                text = (msg.get("text") or "").strip()
                if chat_id != ALLOWED_ID or not text:
                    continue
                print(f"[telegram] << {text[:100]}")
                process(chat_id, text)
        except requests.exceptions.Timeout:
            continue
        except KeyboardInterrupt:
            print("[telegram] stopped")
            break
        except Exception as e:
            print(f"[telegram] error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
