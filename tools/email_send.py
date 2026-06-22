#!/usr/bin/env python3
"""Send email via the local Hydroxide SMTP bridge (Proton).

Hydroxide runs as a user service exposing SMTP on 127.0.0.1:1025 (localhost only).
Auth uses the Proton address + the bridge password hydroxide generated at `auth`
(stored as PROTON_BRIDGE_PASSWORD in ~/.config/agent/secrets.env).

Usage:
  email_send.py <to> <subject> <body...>
"""
import os
import sys
import smtplib
from email.message import EmailMessage
from dotenv import dotenv_values

S = dotenv_values(os.path.expanduser("~/.config/agent/secrets.env"))
FROM = S.get("PROTONMAIL_ANON_EMAIL")
BRIDGE_PW = S.get("PROTON_BRIDGE_PASSWORD")
HOST, PORT = "127.0.0.1", 1025


def send(to: str, subject: str, body: str) -> None:
    if not FROM or not BRIDGE_PW:
        sys.exit("missing PROTONMAIL_ANON_EMAIL / PROTON_BRIDGE_PASSWORD in secrets")
    msg = EmailMessage()
    msg["From"] = FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(HOST, PORT, timeout=30) as s:
        s.ehlo()
        try:
            s.starttls()
            s.ehlo()
        except smtplib.SMTPException:
            pass  # hydroxide localhost may not offer STARTTLS; AUTH over loopback is fine
        s.login(FROM, BRIDGE_PW)
        s.send_message(msg)
    print(f"sent to {to}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: email_send.py <to> <subject> <body...>")
        sys.exit(1)
    send(sys.argv[1], sys.argv[2], " ".join(sys.argv[3:]))
