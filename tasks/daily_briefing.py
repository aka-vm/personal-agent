#!/usr/bin/env python3
"""
Daily briefing — runs at 8am via cron, sends Vineet a morning summary to Telegram:
weather, today's calendar (both accounts), unread email count, pending reminders.

Deterministic and free (no LLM call): it shells out to the existing tools and
assembles the result. Reliable enough to depend on every morning.
"""
import os
import json
import subprocess
import datetime

from notify import send_telegram

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_tool(args, timeout=60):
    """Run a tool from the repo root, return stdout (or '' on failure)."""
    try:
        p = subprocess.run(
            ["python3"] + args, cwd=REPO,
            capture_output=True, text=True, timeout=timeout,
        )
        return p.stdout.strip()
    except Exception as e:
        return f"(error: {e})"


def section_weather():
    out = run_tool(["tools/weather.py", "now"])
    if not out:
        return "Weather unavailable."
    # keep the headline lines only (emoji desc, place, temp) — drop humidity/wind noise
    lines = [l for l in out.splitlines() if l.strip()]
    return "\n".join(lines[:3]) if lines else "Weather unavailable."


def _hhmm(iso):
    try:
        return datetime.datetime.fromisoformat(iso).strftime("%H:%M")
    except Exception:
        return ""


def section_calendar():
    raw = run_tool(["tools/gcal.py", "json-today", "both"])
    try:
        events = json.loads(raw)
    except Exception:
        return "Couldn't load calendar."
    if not events:
        return "Nothing scheduled — clear day 🎉"

    all_day = [e for e in events if e.get("all_day")]
    timed   = sorted([e for e in events if not e.get("all_day")],
                     key=lambda e: e["start"])

    def duration_secs(e):
        try:
            s = datetime.datetime.fromisoformat(e["start"])
            en = datetime.datetime.fromisoformat(e["end"])
            return (en - s).total_seconds()
        except Exception:
            return 999

    meetings = [e for e in timed if duration_secs(e) >= 120]
    blips    = [e for e in timed if duration_secs(e) < 120]   # instant reminders

    lines = []
    for e in all_day:
        lines.append(f"🗓 {e['summary']} — all day")
    for e in meetings:
        tag = "" if e["account"] == "work" else "  _(personal)_"
        lines.append(f"• {_hhmm(e['start'])}–{_hhmm(e['end'])}  {e['summary']}{tag}")
    if blips:
        from collections import Counter
        c = Counter(e["summary"] for e in blips)
        compact = ", ".join(f"{name}×{n}" if n > 1 else name for name, n in c.items())
        lines.append(f"🔔 _{compact}_")
    return "\n".join(lines)


def section_email():
    parts = []
    for acct in ("personal", "work"):
        n = run_tool(["tools/gmail.py", "count", acct, "in:inbox is:unread newer_than:7d"]).strip()
        if n.isdigit() and int(n) > 0:
            parts.append(f"{acct} {n}")
    return (" · ".join(parts) + "  _(unread, last 7d)_") if parts else "all caught up ✨"


def section_reminders():
    out = run_tool(["tools/apple_reminders.py", "list"])
    lines = [l for l in out.splitlines() if l.strip().startswith("○")]
    if not lines:
        return None  # nothing pending → omit section
    return "\n".join(lines)


def main():
    today = datetime.date.today().strftime("%A, %d %B")
    blocks = [f"☀️ *Good morning, Vineet* — {today}", ""]

    blocks.append(section_weather())
    blocks.append("")
    blocks.append("*📅 Today*")
    blocks.append(section_calendar())
    blocks.append("")
    blocks.append(f"*📧 Email:* {section_email()}")

    rem = section_reminders()
    if rem:
        blocks.append("")
        blocks.append("*✅ Reminders*")
        blocks.append(rem)

    send_telegram("\n".join(blocks))


if __name__ == "__main__":
    main()
