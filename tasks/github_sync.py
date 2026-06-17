#!/usr/bin/env python3
"""
Daily GitHub sync — push committed changes to the remote so GitHub always has the
latest. Does NOT auto-commit working-tree changes (that's the agent's job during
sessions); if there are uncommitted changes it just flags them.
"""
import os
import sys
import subprocess
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import config

REPO = config.work_dir


def git(*args):
    return subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True)


def main():
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    dirty = git("status", "--porcelain").stdout.strip()
    push = git("push")
    ok = push.returncode == 0
    out = (push.stdout + push.stderr).strip().splitlines()
    tail = out[-1] if out else "(no output)"
    print(f"[{stamp}] push {'OK' if ok else 'FAILED'}: {tail}")
    if dirty:
        print(f"[{stamp}] note: uncommitted working-tree changes present:\n{dirty}")
    if not ok:
        # surface push failures (e.g. auth) to Vineet
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from notify import send_whatsapp
            send_whatsapp(f"⚠️ GitHub daily sync failed:\n{tail}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
