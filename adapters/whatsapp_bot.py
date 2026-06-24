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
import re
import sys
import json
import time
import uuid
import threading
import urllib.request
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.agent import handle
from core.config import config


def to_whatsapp(md: str) -> str:
    """Convert the agent's markdown into WhatsApp formatting.
    WhatsApp: *bold*, _italic_, no headers/tables. Markdown uses **bold**, ##, |tables|."""
    out = []
    for line in md.split("\n"):
        if re.match(r'^\s*\|?\s*:?-{2,}', line) and line.count("-") >= 2 and "|" in line:
            continue  # drop markdown table separator rows (|---|---|)
        h = re.match(r'^\s*#{1,6}\s+(.*)', line)          # headers -> bold
        if h:
            out.append(f"*{h.group(1).strip()}*"); continue
        b = re.match(r'^(\s*)[-*]\s+(.*)', line)          # bullets -> •
        if b:
            out.append(f"{b.group(1)}• {b.group(2)}"); continue
        out.append(line)
    text = "\n".join(out)
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)        # **bold** -> *bold*
    text = re.sub(r'(?<!\w)__(.+?)__(?!\w)', r'*\1*', text)
    text = re.sub(r'\n{3,}', '\n\n', text)                # collapse blank runs
    return text.strip()

BRIDGE = config.get("whatsapp.bridge_url", "http://localhost:3001")
# /data inside the container maps to this host path
CONTAINER_DATA = "/data"
HOST_DATA = "/mnt/ssd/rpi_storage/whatsapp-baileys"

_secrets = dotenv_values(os.path.expanduser("~/.config/agent/secrets.env"))
GROQ_KEY = _secrets.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY")
CHAT_GROUP = config.get("whatsapp.chat_group")
CONV_KEY = "whatsapp:rpibot"
POLL_INTERVAL = 3
STATE_FILE = os.path.join(config.state_dir, "whatsapp_offset.json")

EXTRA_SYSTEM = (
    "You are talking to Vineet in his private 'RPI bot' WhatsApp group — his "
    "direct line to you, like a chat. Keep replies short and chat-style. "
    "Format for WhatsApp, NOT markdown: use *single asterisks* for bold, no "
    "# headings, no tables, no **double asterisks**. Short lines and simple "
    "• bullets. To send a file, output a line `SEND_FILE:/abs/path`."
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
    r = api_post("/send-group", {"groupId": CHAT_GROUP, "message": message})
    return r.get("key") if r else None


def reply_file(path):
    api_post("/send-file", {"groupId": CHAT_GROUP, "filePath": path.strip()})


def edit_message(key, message):
    """Edit a previously-sent message in place (key from reply_text)."""
    if key:
        api_post("/edit", {"groupId": CHAT_GROUP, "key": key, "message": message})


def set_presence(state):
    """state: composing (typing…) | paused | available"""
    api_post("/presence", {"groupId": CHAT_GROUP, "state": state})


def react_to(msg, emoji):
    """React to an incoming group message (msg = a /messages entry)."""
    api_post("/react", {"groupId": CHAT_GROUP, "id": msg.get("id"),
                        "participant": msg.get("participant"), "fromMe": False,
                        "emoji": emoji})


def load_offset():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE)).get("last_ts", 0)
        except Exception:
            return 0
    return 0


def save_offset(ts):
    json.dump({"last_ts": ts}, open(STATE_FILE, "w"))


def transcribe_voice(container_path: str) -> str | None:
    if not GROQ_KEY:
        print("[whatsapp] no GROQ_API_KEY — cannot transcribe voice")
        return None
    host_path = container_path.replace(CONTAINER_DATA, HOST_DATA, 1)
    if not os.path.isfile(host_path):
        print(f"[whatsapp] voice file not found: {host_path}")
        return None
    with open(host_path, "rb") as f:
        audio_data = f.read()
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="model"\r\n\r\n'
        f"whisper-large-v3\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="language"\r\n\r\n'
        f"en\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="prompt"\r\n\r\n'
        f"Voice message to an AI assistant. Indian English.\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="voice.ogg"\r\n'
        f"Content-Type: audio/ogg\r\n\r\n"
    ).encode() + audio_data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {GROQ_KEY}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            # Groq is behind Cloudflare, which 403s urllib's default User-Agent.
            "User-Agent": "curl/8.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            transcript = json.loads(r.read()).get("text", "").strip()
            print(f"[whatsapp] transcribed: {transcript[:80]}")
            return transcript
    except Exception as e:
        print(f"[whatsapp] transcription error: {e}")
        return None


def _split_message(text: str, limit: int = 4000) -> list[str]:
    """Split at paragraph boundaries to avoid cutting mid-word."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut == -1:
            cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks


# Conservative model routing: only obvious chit-chat (greetings/acks/thanks) goes
# to the cheap model. Anything with a "?" or a task verb stays on the default
# (stronger) model — we only ever DOWNgrade when it's clearly safe. No extra LLM call.
_TRIVIAL = re.compile(
    r'^(hi+|hey+|hello|yo|ok(ay)?|kk|thx|thanks?|thank you|ty|cool|nice|great|'
    r'done|got ?it|gotcha|haha+|lol|gm|gn|good ?(morning|night|evening|afternoon)|'
    r'sup|np|no problem|👍|🙏|🙌|😄|😂)[!.\s]*$', re.I)

def pick_model(text):
    t = (text or "").strip()
    if len(t) <= 40 and "?" not in t and _TRIVIAL.match(t):
        return config.cheap_model      # trivial → Haiku
    return None                         # everything else → default (Sonnet)


def process(text):
    # Send a placeholder we'll EDIT in place into the final answer, and show
    # "typing…" (kept alive on a timer) while claude is thinking.
    key = reply_text("⏳ ...")
    set_presence("composing")
    stop = threading.Event()

    def _keep_typing():
        while not stop.wait(8):       # WhatsApp clears typing after ~25s; refresh it
            set_presence("composing")

    t = threading.Thread(target=_keep_typing, daemon=True)
    t.start()
    try:
        reply = handle(text, CONV_KEY, extra_system=EXTRA_SYSTEM, model=pick_model(text))
    finally:
        stop.set()
        set_presence("paused")

    if reply.error:
        msg = f"⚠️ {reply.error}"
        edit_message(key, msg) if key else reply_text(msg)
        return

    if reply.text:
        formatted = to_whatsapp(reply.text)
        chunks = _split_message(formatted) or [""]
        # Edit the placeholder into the first chunk; send any overflow as new messages.
        if key:
            edit_message(key, chunks[0])
        else:
            reply_text(chunks[0])
        for c in chunks[1:]:
            reply_text(c)
    elif key:
        edit_message(key, "✅")        # no text (e.g. file-only reply) — clear the ⏳

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
                voice_path = m.get("voicePath")

                # transcribe voice if no text but voice file present
                if not txt and voice_path:
                    transcript = transcribe_voice(voice_path)
                    if transcript:
                        txt = f"[Voice message]: {transcript}"

                if txt:
                    quoted = (m.get("quoted") or "").strip()
                    if quoted:
                        full = f'(In reply to: "{quoted[:500]}")\n\n{txt}'
                    else:
                        full = txt
                    print(f"[whatsapp] << {txt[:80]}" + (" [reply]" if quoted else ""))
                    react_to(m, "👀")     # acknowledge receipt
                    process(full)
                    react_to(m, "✅")     # done
                last_ts = max(last_ts, m.get("timestamp", 0))
                save_offset(last_ts)
        except Exception as e:
            print(f"[whatsapp] error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
