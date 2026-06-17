#!/usr/bin/env python3
"""
Weekly full-system-review nudge. Runs daily; only sends if it's been >= 7 days
since the last *completed* review (recorded by review_done.py). That gives a
weekly cadence AND a ~24h re-nudge until Vineet gives the go-ahead.

The review itself is interactive (Vineet replies, then the agent reviews end-to-end
with the best model). This script only reminds.
"""
import os
import sys
import json
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.config import config
from notify import send_whatsapp

STATE = os.path.join(config.state_dir, "review_state.json")
INTERVAL_DAYS = 7


def load():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE))
        except Exception:
            pass
    return {"last_review": None, "history": []}


def days_since(d):
    if not d:
        return 99999
    try:
        return (datetime.date.today() - datetime.date.fromisoformat(d)).days
    except Exception:
        return 99999


def main():
    s = load()
    n = days_since(s.get("last_review"))
    if n < INTERVAL_DAYS:
        return  # not due yet — stay quiet
    last = "never" if n >= 99999 else f"{n} days ago"
    msg = (
        f"🔍 *Weekly system review due* (last: {last})\n\n"
        "Reply *review* and I'll go end-to-end with the best model on:\n"
        "• Stability & reliability\n"
        "• Reducing complexity where possible\n"
        "• System + LLM-usage optimization\n"
        "• Good engineering practices\n\n"
        "_I'll remind again in ~24h until we do it._"
    )
    send_whatsapp(msg)


if __name__ == "__main__":
    main()
