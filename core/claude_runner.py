"""
ClaudeRunner — wraps the `claude` CLI in headless (-p) mode with native session
resume. This replaces hand-built conversation-history strings: Claude Code
persists the full session (including tool calls) and we just resume it by id.

One session id per conversation key (e.g. "telegram:908337362"). Persisted to
disk so conversations survive bot restarts.
"""
import json
import os
import subprocess
import time
import uuid

from .config import config

CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")
SESSIONS_FILE = os.path.join(config.state_dir, "sessions.json")


def _load_sessions() -> dict:
    if os.path.exists(SESSIONS_FILE):
        try:
            return json.load(open(SESSIONS_FILE))
        except Exception:
            return {}
    return {}


def _save_sessions(data: dict):
    tmp = SESSIONS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, SESSIONS_FILE)


class ClaudeRunner:
    def __init__(self):
        self.model = config.model
        self.work_dir = config.work_dir
        self.timeout = config.timeout
        self.session_timeout = config.session_timeout
        self.session_max_age = config.session_max_age

    # ── session bookkeeping ──────────────────────────────────────────────────

    def _get_session_id(self, conv_key: str):
        sessions = _load_sessions()
        entry = sessions.get(conv_key)
        if not entry:
            return None
        now = time.time()
        # reset on long silence — keeps each conversation burst self-contained
        if self.session_timeout and (now - entry.get("last_ts", 0)) > self.session_timeout:
            return None
        # hard cap on total session age — bounds context growth even in active chats
        if self.session_max_age and (now - entry.get("started_ts", now)) > self.session_max_age:
            return None
        return entry.get("session_id")

    def _store_session_id(self, conv_key: str, session_id: str):
        sessions = _load_sessions()
        prev = sessions.get(conv_key, {})
        # keep the original start time while the same session continues; new id resets it
        started = prev.get("started_ts") if prev.get("session_id") == session_id else None
        sessions[conv_key] = {"session_id": session_id,
                              "started_ts": started or time.time(),
                              "last_ts": time.time()}
        _save_sessions(sessions)

    def reset(self, conv_key: str):
        """Forget the conversation — next run starts a fresh session."""
        sessions = _load_sessions()
        if conv_key in sessions:
            del sessions[conv_key]
            _save_sessions(sessions)

    # ── invocation ───────────────────────────────────────────────────────────

    def _invoke(self, text: str, session_id: str, resume: bool, extra_system: str | None, model: str | None = None):
        cmd = [
            CLAUDE_BIN, "-p", text,
            "--model", model or self.model,
            "--output-format", "json",
            "--permission-mode", "bypassPermissions",
        ]
        if resume:
            cmd += ["--resume", session_id]
        else:
            cmd += ["--session-id", session_id]
        if extra_system:
            cmd += ["--append-system-prompt", extra_system]

        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=self.work_dir, timeout=self.timeout,
        )
        return proc

    def run(self, text: str, conv_key: str, extra_system: str | None = None, model: str | None = None) -> dict:
        """
        Run one turn. Returns {ok, result, session_id, cost, error}.
        Resumes the conversation's session if one exists, else starts a new one.
        Falls back to a fresh session if resume fails (e.g. session pruned).
        """
        session_id = self._get_session_id(conv_key)
        resume = session_id is not None
        if not session_id:
            session_id = str(uuid.uuid4())

        try:
            proc = self._invoke(text, session_id, resume, extra_system, model)
            # If resume failed (stale/missing session), retry once with a new session.
            if resume and proc.returncode != 0 and "session" in (proc.stderr or "").lower():
                session_id = str(uuid.uuid4())
                resume = False
                proc = self._invoke(text, session_id, resume, extra_system, model)
        except subprocess.TimeoutExpired:
            return {"ok": False, "result": "", "session_id": session_id,
                    "cost": 0, "error": f"Timed out after {self.timeout}s"}
        except Exception as e:
            return {"ok": False, "result": "", "session_id": session_id,
                    "cost": 0, "error": str(e)}

        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()

        # Parse the JSON envelope claude --output-format json returns.
        result_text, cost, real_sid = out, 0, session_id
        try:
            data = json.loads(out)
            result_text = data.get("result", out)
            cost = data.get("total_cost_usd", 0)
            real_sid = data.get("session_id", session_id)
        except (json.JSONDecodeError, AttributeError):
            pass

        if proc.returncode != 0 and not result_text:
            return {"ok": False, "result": "", "session_id": session_id,
                    "cost": 0, "error": err or "claude exited with an error"}

        self._store_session_id(conv_key, real_sid)
        return {"ok": True, "result": result_text or "(no output)",
                "session_id": real_sid, "cost": cost, "error": None}


runner = ClaudeRunner()
