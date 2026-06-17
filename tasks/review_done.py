#!/usr/bin/env python3
"""
Record a completed full-system review. The agent runs this AFTER a review where
P0/P1 issues are scanned + fixed (P2+ may remain): it checkpoints the current git
commit as a known-good reviewed state and resets the weekly nudge timer.

Usage: review_done.py "<one-line summary of what was reviewed/fixed>"
"""
import os
import sys
import json
import subprocess
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import config

REPO = config.work_dir
STATE = os.path.join(config.state_dir, "review_state.json")


def load():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE))
        except Exception:
            pass
    return {"last_review": None, "history": []}


def main():
    summary = " ".join(sys.argv[1:]).strip() or "full system review"
    commit = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()[:12]
    today = datetime.date.today().isoformat()
    s = load()
    s["last_review"] = today
    s.setdefault("history", []).append({"date": today, "commit": commit, "summary": summary})
    json.dump(s, open(STATE, "w"), indent=2)
    print(f"✓ Review checkpointed: {today} @ {commit} — {summary}")
    print(f"  ({len(s['history'])} reviews on record; next nudge in 7 days)")


if __name__ == "__main__":
    main()
