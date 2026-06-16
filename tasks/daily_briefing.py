#!/usr/bin/env python3
"""
Daily briefing — 8am. Agent-powered so it follows Vineet's preferences (email
summary format, IST, WhatsApp formatting) from CLAUDE.md + memory. Delivered to
the RPI bot WhatsApp group (the active channel; Telegram is blocked).

Falls back to a terse deterministic note if the agent call fails, so a morning
is never silent.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.claude_runner import runner
from notify import send_whatsapp

PROMPT = (
    "Generate my morning briefing. Include, concise and WhatsApp-formatted "
    "(*bold*, • bullets, no markdown headings/tables):\n"
    "1. Weather now (one line).\n"
    "2. Today's calendar across both accounts, in IST, each with its event link.\n"
    "3. Email per my saved email-summary format (actionable from last 1 day, "
    "important unread from last 3 days; lead with work; group by urgency).\n"
    "Keep it tight — it's a glanceable morning summary, not a report."
)


def main():
    try:
        res = runner.run(PROMPT, "task:daily-briefing")
        text = res.get("result") if res.get("ok") else None
    except Exception as e:
        text = None
        print(f"[briefing] agent error: {e}")

    if text:
        send_whatsapp(text)
    else:
        # never go silent
        send_whatsapp("☀️ Morning! (Couldn't build the full briefing — "
                      "ask me for your calendar/weather/email when ready.)")


if __name__ == "__main__":
    main()
