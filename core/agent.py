"""
Agent core — the single brain both the Telegram and WhatsApp adapters call.

Responsibilities:
  - run a turn through ClaudeRunner (native session resume)
  - handle built-in commands (/reset, /status, /help)
  - extract SEND_FILE: markers so adapters can deliver files
Long-term memory is NOT handled here: the agent uses Claude Code's native memory
(MEMORY.md, imported by CLAUDE.md) and updates it with its own tools.
"""
import os
import re
from dataclasses import dataclass, field

from .claude_runner import runner
from .config import config

SEND_FILE_RE = re.compile(r'^SEND_FILE:(.+)$', re.MULTILINE)
ALLOWED_SEND_DIRS = ["/mnt/ssd/", "/home/vineet/"]

# Conservative model routing: only obvious chit-chat (greetings/acks/thanks) is
# DOWNgraded to the cheap model. Anything with a "?" or a task verb stays on the
# default (stronger) model — we only ever downgrade when it's clearly safe.
_TRIVIAL_RE = re.compile(
    r'^(hi+|hey+|hello|yo|ok(ay)?|kk|thx|thanks?|thank you|ty|cool|nice|great|'
    r'done|got ?it|gotcha|haha+|lol|gm|gn|good ?(morning|night|evening|afternoon)|'
    r'sup|np|no problem|👍|🙏|🙌|😄|😂)[!.\s]*$', re.I)


def pick_model(text: str) -> str | None:
    """Cheap model for trivial chit-chat, else None (adapter's default). No LLM call."""
    t = (text or "").strip()
    if len(t) <= 40 and "?" not in t and _TRIVIAL_RE.match(t):
        return config.cheap_model
    return None


@dataclass
class Reply:
    text: str = ""
    files: list = field(default_factory=list)
    error: str | None = None
    cost: float = 0.0


def _path_allowed(path: str) -> bool:
    real = os.path.realpath(path.strip())
    return any(real.startswith(d) for d in ALLOWED_SEND_DIRS)


def handle(text: str, conv_key: str, extra_system: str | None = None, model: str | None = None,
           allowed_tools=None, work_dir: str | None = None) -> Reply:
    text = (text or "").strip()
    if not text:
        return Reply()

    # Restricted (untrusted group) turns skip the built-in owner commands entirely.
    if allowed_tools is not None:
        res = runner.run(text, conv_key, extra_system=extra_system, model=model,
                         allowed_tools=allowed_tools, work_dir=work_dir)
        if not res["ok"]:
            return Reply(error=res["error"])
        raw = res["result"]
        # No SEND_FILE handling for restricted turns — they cannot deliver files.
        return Reply(text=raw, cost=res.get("cost", 0))

    # ── built-in commands ────────────────────────────────────────────────────
    low = text.lower()
    if low in ("/reset", "/start", "/new"):
        runner.reset(conv_key)
        return Reply(text="🧹 Conversation cleared. Starting fresh.")
    if low == "/status":
        from .claude_runner import _load_sessions
        s = _load_sessions().get(conv_key)
        sid = s["session_id"][:8] if s else "none"
        return Reply(text=f"🤖 Online\nModel: {config.model}\nSession: {sid}")
    if low == "/help":
        return Reply(text=(
            "Commands:\n"
            "/reset — forget this conversation\n"
            "/status — show agent status\n"
            "/help — this message\n\n"
            "Otherwise just talk to me. I remember across restarts and "
            "keep long-term memory of your preferences."
        ))

    # ── run the turn ─────────────────────────────────────────────────────────
    res = runner.run(text, conv_key, extra_system=extra_system, model=model)
    if not res["ok"]:
        return Reply(error=res["error"])

    raw = res["result"]
    files = [p.strip() for p in SEND_FILE_RE.findall(raw) if _path_allowed(p)]
    clean = SEND_FILE_RE.sub("", raw).strip()
    return Reply(text=clean, files=files, cost=res.get("cost", 0))
