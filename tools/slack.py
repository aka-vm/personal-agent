#!/usr/bin/env python3
"""
Slack presence/status control. The token is scoped to WRITES only
(users.profile:write, users:write, dnd:write) — this tool cannot read messages.

Reads SLACK_USER_TOKEN (xoxp-...) from ~/.config/agent/secrets.env.

Usage:
  slack.py status "<text>" [:emoji:] [minutes]   # custom status; minutes=auto-expire (0=permanent)
  slack.py clear                                  # clear status
  slack.py away | active                          # set presence
  slack.py dnd on [minutes] | dnd off             # mute (DND); default 60 min
"""
import sys, os, time, json
import requests
from dotenv import dotenv_values

SECRETS = os.path.expanduser("~/.config/agent/secrets.env")


def _token():
    t = (dotenv_values(SECRETS).get("SLACK_USER_TOKEN") if os.path.exists(SECRETS) else None) \
        or os.environ.get("SLACK_USER_TOKEN")
    if not t:
        print("No SLACK_USER_TOKEN in ~/.config/agent/secrets.env "
              "(create a Slack app with users.profile:write, users:write, dnd:write).")
        sys.exit(1)
    return t


def _call(method, data):
    r = requests.post(f"https://slack.com/api/{method}",
                      headers={"Authorization": f"Bearer {_token()}"},
                      data=data, timeout=15)
    return r.json()


def cmd_status(text, emoji="", minutes=0):
    exp = int(time.time()) + int(minutes) * 60 if int(minutes) else 0
    profile = {"status_text": text, "status_emoji": emoji, "status_expiration": exp}
    j = _call("users.profile.set", {"profile": json.dumps(profile)})
    tail = f" (clears in {minutes}m)" if minutes else ""
    print(f"✓ Status: {emoji} {text}{tail}" if j.get("ok") else f"Error: {j.get('error')}")


def cmd_clear():
    j = _call("users.profile.set",
              {"profile": json.dumps({"status_text": "", "status_emoji": "", "status_expiration": 0})})
    print("✓ Status cleared" if j.get("ok") else f"Error: {j.get('error')}")


def cmd_presence(p):  # "away" or "auto"
    j = _call("users.setPresence", {"presence": p})
    label = "away" if p == "away" else "active"
    print(f"✓ Presence: {label}" if j.get("ok") else f"Error: {j.get('error')}")


def cmd_dnd_on(minutes=60):
    j = _call("dnd.setSnooze", {"num_minutes": int(minutes)})
    print(f"✓ DND on for {minutes} min" if j.get("ok") else f"Error: {j.get('error')}")


def cmd_dnd_off():
    j = _call("dnd.endSnooze", {})
    print("✓ DND off" if j.get("ok") else f"Error: {j.get('error')}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__); sys.exit(0)
    c = args[0]
    if c == "status":
        emoji, minutes, text_parts = "", 0, []
        for a in args[1:]:
            if a.startswith(":") and a.endswith(":") and len(a) > 2:
                emoji = a
            elif a.isdigit():
                minutes = int(a)
            else:
                text_parts.append(a)
        cmd_status(" ".join(text_parts), emoji, minutes)
    elif c == "clear":
        cmd_clear()
    elif c == "away":
        cmd_presence("away")
    elif c == "active":
        cmd_presence("auto")
    elif c == "dnd":
        sub = args[1] if len(args) > 1 else ""
        if sub == "on":
            cmd_dnd_on(args[2] if len(args) > 2 else 60)
        elif sub == "off":
            cmd_dnd_off()
        else:
            print("Usage: slack.py dnd on [minutes] | dnd off")
    else:
        print(__doc__)
