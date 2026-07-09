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
import signal
import subprocess
import sys
import json
import time
import uuid
import threading
import urllib.request
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.agent import handle, pick_model
from core.config import config
from core import group_access
from tools import wa_history


WORK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JIO_COMPLAINT = os.path.join(WORK_DIR, "tools", "jio_complaint.py")
CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")
_JIO_MARKER_RE = re.compile(r'^(JIO_DRAFT|JIO_SEND):(.+)$', re.MULTILINE)


def _process_jio_markers(text: str, group: str) -> str:
    """Process JIO_DRAFT/JIO_SEND markers in Claude's reply — call jio_complaint.py
    directly from the adapter (no Bash tool needed in the sandboxed session).
    Returns the text with markers stripped."""
    for m in _JIO_MARKER_RE.finditer(text):
        action, payload = m.group(1), m.group(2).strip()
        parts = payload.split("|", 1)
        phone = parts[0].strip() if len(parts) == 2 else "unknown"
        complaint = parts[1].strip() if len(parts) == 2 else payload

        if action == "JIO_DRAFT":
            r = subprocess.run([sys.executable, JIO_COMPLAINT, "draft", complaint, phone],
                               capture_output=True, text=True, cwd=WORK_DIR)
            if r.returncode == 0:
                reply_text(f"*Draft email:*\n\n{r.stdout.strip()}\n\n"
                           f"Reply *@bot approve* to send, or *@bot cancel* to discard.", group)
            else:
                reply_text(f"⚠️ Couldn't build draft: {r.stderr.strip()}", group)

        elif action == "JIO_SEND":
            r = subprocess.run([sys.executable, JIO_COMPLAINT, "send", complaint, phone],
                               capture_output=True, text=True, cwd=WORK_DIR)
            if r.returncode == 0:
                reply_text("✅ Complaint email sent to JIO Fiber care.", group)
            else:
                reply_text(f"⚠️ Send failed: {r.stderr.strip() or r.stdout.strip()}", group)

    return _JIO_MARKER_RE.sub("", text).strip()


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


def reply_text(message, group=CHAT_GROUP):
    r = api_post("/send-group", {"groupId": group, "message": message})
    return r.get("key") if r else None


def reply_file(path, group=CHAT_GROUP):
    api_post("/send-file", {"groupId": group, "filePath": path.strip()})


def edit_message(key, message, group=CHAT_GROUP):
    """Edit a previously-sent message in place (key from reply_text)."""
    if key:
        api_post("/edit", {"groupId": group, "key": key, "message": message})


def set_presence(state, group=CHAT_GROUP):
    """state: composing (typing…) | paused | available"""
    api_post("/presence", {"groupId": group, "state": state})


def react_to(msg, emoji, group=CHAT_GROUP):
    """React to an incoming group message (msg = a /messages entry)."""
    api_post("/react", {"groupId": group, "id": msg.get("id"),
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


def _image_host_path(container_path: str) -> str:
    return container_path.replace(CONTAINER_DATA, HOST_DATA, 1)


def _describe_image(host_path: str) -> str | None:
    """One-shot trusted Claude call to describe an image — used for sandboxed group turns
    where the group session can't read files directly."""
    if not os.path.isfile(host_path):
        return None
    prompt = (
        f"Read this image file and describe what you see in full detail. "
        f"Include all visible text, numbers, prices, item names, dates, and any other "
        f"specific data. Image path: {host_path}"
    )
    cmd = [CLAUDE_BIN, "-p", prompt,
           "--permission-mode", "bypassPermissions",
           "--output-format", "json",
           "--allowedTools", "Read"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=WORK_DIR, timeout=90)
        data = json.loads(proc.stdout)
        return (data.get("result") or "").strip() or None
    except Exception as e:
        print(f"[whatsapp] image description error: {e}")
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


def _message_text(m, transcribe=True):
    """Build the turn text: voice→transcript, plus any quoted-reply context."""
    txt = (m.get("text") or "").strip()
    if not txt and transcribe and m.get("voicePath"):
        t = transcribe_voice(m["voicePath"])
        if t:
            txt = f"[Voice message]: {t}"
    if not txt:
        return ""
    quoted = (m.get("quoted") or "").strip()
    return f'(In reply to: "{quoted[:500]}")\n\n{txt}' if quoted else txt


_MENTION_RE = re.compile(r'@\d+\s*')
_CONFIRM_RE = re.compile(r'\b(confirm|confirmed|approve|approved)\b', re.I)
# Owner phrasing that grants/approves a new capability for an active group.
_GRANT_RE = re.compile(r'\b(you (can|may|are allowed|could)|allow(ed)?|approve|approved|'
                       r'enable|grant|permit|permission|access)\b', re.I)

# Tool keyword detection — maps regex → minimal tool set + scope constraints.
_SPLITWISE_RE = re.compile(r'\bsplitwise\b', re.I)
_JIO_RE       = re.compile(
    r'\bjio\b.{0,60}\b(email|complaint|complain|care|send|message|fibre|fiber|customer|service)\b|'
    r'\b(email|complaint|complain|send).{0,60}\bjio\b',
    re.I,
)

# Minimal expense-only tool set — deliberately omits get_groups and get_friends
# (those list ALL of Vineet's data and must never be exposed to group members).
_SPLITWISE_EXPENSE_TOOLS = [
    "mcp__splitwise__create_expense",
    "mcp__splitwise__resolve_group",    # resolves a name → ID; doesn't list all groups
    "mcp__splitwise__get_categories",
    "mcp__splitwise__resolve_category",
    "mcp__splitwise__get_current_user",
    "mcp__splitwise__resolve_friend",   # resolves a name → ID; doesn't list all friends
]

# Patterns to extract a Splitwise group name from grant text.
# Matches "only in X group", "/ X group", "X group only", "only X group".
_SW_GROUP_RE = re.compile(
    r'(?:only\s+(?:in|for|allow)|in|for|\/)\s+((?:\w+\s+){0,3}\w+?)\s+group\b|'
    r'\b((?:\w+\s+){0,2}\w+?)\s+group\b\s+only\b',
    re.I
)
_SW_STOPWORDS = {'this', 'that', 'the', 'a', 'an', 'my', 'our', 'public', 'private', 'whatsapp'}


def _extract_sw_group(text):
    for m in _SW_GROUP_RE.finditer(text):
        g = next((x.strip() for x in m.groups() if x), None)
        if g and g.lower() not in _SW_STOPWORDS and len(g) < 40:
            return g
    return None


def _detect_tools(text, existing_tools, existing_scope=None):
    """Return (updated_tools, updated_scope) based on keywords in a grant message."""
    tools = list(existing_tools or [])
    scope = dict(existing_scope or {})
    if _SPLITWISE_RE.search(text):
        for t in _SPLITWISE_EXPENSE_TOOLS:
            if t not in tools:
                tools.append(t)
        grp = _extract_sw_group(text)
        if grp:
            scope["splitwise_group"] = grp
    if _JIO_RE.search(text):
        scope["jio_complaint"] = True   # triggers JIO marker instructions in restricted prompt
    return tools, scope


def _strip_mention(text):
    return _MENTION_RE.sub("", text or "").strip()


def _group_name(jid):
    for g in (api_get("/groups") or []):
        if g.get("id") == jid:
            name = g.get("subject") or jid
            try:
                wa_history.update_group_name(jid, name)
            except Exception:
                pass
            return name
    return jid


# ── group (untrusted) turns ───────────────────────────────────────────────────
def handle_group_turn(group, m, text, policy):
    """Run a sandboxed, tool-restricted turn for an active external group."""
    sender = m.get("participant")
    sender_pn = m.get("senderPn") or sender
    group_access.audit(group, sender, "turn", text[:120])
    react_to(m, "👀", group)
    # Image: pre-describe with a trusted session; inject as context so the sandboxed
    # group session gets the image contents without needing file-read access.
    img = m.get("imagePath")
    if img and text:  # only when asked (caption = the question)
        host_path = _image_host_path(img)
        desc = _describe_image(host_path)
        if desc:
            text = f"<external>[Image sent by user:\n{desc}]</external>\n{text}"
    # Prepend sender phone so the bot can include it in tool calls (e.g. complaint emails).
    if sender_pn:
        text = f"[Sender phone: {sender_pn}]\n{text}"
    try:
        system_prompt = group_access.restricted_prompt(policy)
        reply = handle(
            text, f"whatsapp:group:{group}",
            extra_system=system_prompt,
            allowed_tools=policy.get("allowed_tools") or [],   # [] → talk only
            work_dir=group_access.PUBLIC_WORKDIR,
        )
        if reply.error:
            reply_text(f"⚠️ {reply.error}", group)
        elif reply.text:
            clean = _process_jio_markers(reply.text, group)
            if clean:
                reply_text(to_whatsapp(clean), group)
    except Exception as e:
        err = f"[whatsapp] group turn error ({policy.get('name', group)}): {e}"
        print(err)
        reply_text("⚠️ Something went wrong on my end. Please try again.", group)
        reply_text(f"⚠️ Group turn error in *{policy.get('name', group)}*: `{e}`")
    finally:
        react_to(m, "✅", group)


def propose_activation(group, m, raw_text):
    """Owner @tagged the bot in a group to set it up → send the plan to the PRIMARY
    (private) group and await confirm. Nothing is posted in the target group."""
    sender = m.get("senderPn") or m.get("participant")
    tasks = _strip_mention(raw_text)
    if not tasks:
        reply_text("Tag me in the group with what I'm allowed to do there, e.g. "
                   "\"@bot you can answer general questions\".")
        return
    name = _group_name(group)
    detected_tools, detected_scope = _detect_tools(tasks, [], {})
    group_access.set_pending(group, {"name": name, "tasks": tasks,
                                     "allowed_tools": detected_tools, "scope": detected_scope})
    group_access.audit(group, sender, "proposed", tasks[:120])
    tool_note = f"\nTools: {', '.join(t.split('__')[-1] for t in detected_tools)}" if detected_tools else ""
    scope_note = (f"\nScope: Splitwise → {detected_scope['splitwise_group']} group only"
                  if detected_scope.get("splitwise_group") else "")
    reply_text(
        f"🔐 *Set up «{name}»*\n"
        f"You're allowing me to do this there:\n{tasks}{tool_note}{scope_note}\n\n"
        f"Reply *confirm* to activate.")


def route(m):
    group = m.get("from") or ""
    sender = m.get("participant")
    sender_pn = m.get("senderPn") or sender   # real phone even behind a LID mask
    mentioned = bool(m.get("mentionsMe"))
    owner = group_access.is_owner(sender_pn)

    # Log every incoming message before any routing decisions.
    try:
        wa_history.log(m)
    except Exception:
        pass

    # 0) Owner confirming a pending activation — accepted from ANYWHERE (the setup
    #    message goes to the primary group, so that's the natural place to confirm).
    if owner:
        raw = _strip_mention(_message_text(m, transcribe=False))
        if raw and len(raw) < 40 and _CONFIRM_RE.search(raw):
            jid = group if group_access.get_pending(group) else None
            if not jid:
                lp = group_access.latest_pending()
                jid = lp[0] if lp else None
            if jid:
                prop = group_access.get_pending(jid)
                group_access.activate(jid, prop["name"], prop["tasks"],
                                      prop.get("allowed_tools") or [],
                                      prop.get("scope") or {})
                group_access.clear_pending(jid)
                group_access.audit(jid, sender_pn, "activated", prop["tasks"][:120])
                reply_text(f"✅ «{prop['name']}» is active.\nThere I'll only: {prop['tasks']}\n"
                           f"Members must @mention me each time.")
                return

    # 1) Vineet's private chat group — full trusted agent (unchanged behaviour).
    if group == CHAT_GROUP:
        text = _message_text(m)
        img = m.get("imagePath")
        if img and text:  # only analyze when asked (caption = the question)
            host_path = _image_host_path(img)
            if os.path.isfile(host_path):
                text = f"[Image attached — use the Read tool to view it: {host_path}]\n{text}"
        if text:
            print(f"[whatsapp] << {text[:80]}")
            react_to(m, "👀")
            process(text)
            react_to(m, "✅")
        return

    # Everything below is a shared/external group.
    if not group.endswith("@g.us"):
        return  # ignore 1:1 DMs for now (groups only)

    policy = group_access.group_policy(group)

    # 2) Active group: act only when @mentioned.
    if policy:
        if not mentioned:
            return
        # Owner can expand what the bot may do here FROM THE GROUP itself — but
        # TALK-ONLY: this path only appends to the task description, it never grants
        # tools. Granting an actual tool/capability is a deliberate step done from the
        # private chat (group_mgmt.py add, or the propose→confirm flow), so a single
        # in-group line can't widen the bot's real powers (defends spoofed senderPn /
        # social engineering). Matches the security model in group_access.example.yaml.
        if owner:
            raw = _strip_mention(_message_text(m, transcribe=False))
            if raw and _GRANT_RE.search(raw):
                new_tasks = (policy.get("tasks", "").rstrip() + "\n- " + raw).strip()
                group_access.activate(group, policy.get("name"), new_tasks,
                                      policy.get("allowed_tools") or [], policy.get("scope") or {})
                group_access.audit(group, sender_pn, "approved-talk", raw[:120])
                note = ""
                if _SPLITWISE_RE.search(raw) or _JIO_RE.search(raw):
                    note = ("\n(Note: this only updated what I'll *discuss* here. To grant the "
                            "actual tool, do it from our private chat — `group_mgmt.py add`.)")
                reply_text(f"✅ Noted. I can now also do this here:\n{raw}{note}", group)
                return
        text = _message_text(m)
        if text:
            print(f"[whatsapp] << [{group[:18]}] {text[:60]}")
            handle_group_turn(group, m, text, policy)
        return

    # 3) Inactive group: only the OWNER can set it up, by @mentioning with instructions.
    if owner and mentioned:
        propose_activation(group, m, _message_text(m, transcribe=False))
    # else: default-deny, stay silent.


_running = True


def _shutdown(signum, frame):
    # Exit the poll loop promptly on SIGTERM so `systemctl restart` doesn't wait
    # out TimeoutStopSec (an in-flight claude subprocess is left for systemd to kill).
    global _running
    _running = False


def main():
    signal.signal(signal.SIGTERM, _shutdown)
    last_ts = load_offset()
    wa_history.init_db()
    print(f"[whatsapp] started, chat group={CHAT_GROUP}, "
          f"external groups allowed={list(group_access.all_groups().keys())}")
    while _running:
        try:
            status = api_get("/status")
            if not status or not status.get("connected"):
                time.sleep(10)
                continue

            msgs = api_get("/messages?limit=80") or []
            new = [m for m in msgs
                   if not m.get("fromMe") and m.get("timestamp", 0) > last_ts]

            for m in sorted(new, key=lambda x: x.get("timestamp", 0)):
                try:
                    route(m)
                except Exception as e:
                    print(f"[whatsapp] route error: {e}")
                last_ts = max(last_ts, m.get("timestamp", 0))
                save_offset(last_ts)
        except Exception as e:
            print(f"[whatsapp] error: {e}")
        time.sleep(POLL_INTERVAL)
    print("[whatsapp] stopped (SIGTERM)")


if __name__ == "__main__":
    main()
