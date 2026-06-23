#!/usr/bin/env python3
"""Send email via the local Hydroxide SMTP bridge (Proton).

Hydroxide runs as a user service exposing SMTP on 127.0.0.1:1025 (localhost only).
Auth uses the Proton address + the bridge password hydroxide generated at `auth`
(stored as PROTON_BRIDGE_PASSWORD in ~/.config/agent/secrets.env).

Usage:
  email_send.py <to> <subject> <body...> [--attach /path/to/file ...]
"""
import mimetypes
import os
import sys
import smtplib
from email.message import EmailMessage
from dotenv import dotenv_values

S = dotenv_values(os.path.expanduser("~/.config/agent/secrets.env"))
FROM = S.get("PROTONMAIL_ANON_EMAIL")
BRIDGE_PW = S.get("PROTON_BRIDGE_PASSWORD")
HOST, PORT = "127.0.0.1", 1025


def send(to: str, subject: str, body: str, attachments: list[str] = None) -> None:
    if not FROM or not BRIDGE_PW:
        sys.exit("missing PROTONMAIL_ANON_EMAIL / PROTON_BRIDGE_PASSWORD in secrets")
    msg = EmailMessage()
    msg["From"] = FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    for path in (attachments or []):
        mime, _ = mimetypes.guess_type(path)
        maintype, subtype = (mime or "application/octet-stream").split("/", 1)
        with open(path, "rb") as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype,
                               filename=os.path.basename(path))
    with smtplib.SMTP(HOST, PORT, timeout=30) as s:
        s.ehlo()
        try:
            s.starttls()
            s.ehlo()
        except smtplib.SMTPException:
            pass  # hydroxide localhost may not offer STARTTLS; AUTH over loopback is fine
        s.login(FROM, BRIDGE_PW)
        s.send_message(msg)
    print(f"sent to {to}" + (f" with {len(attachments)} attachment(s)" if attachments else ""))


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 3:
        print("usage: email_send.py <to> <subject> <body...> [--attach /path ...]")
        sys.exit(1)
    attach_idx = next((i for i, a in enumerate(args) if a == "--attach"), None)
    if attach_idx is not None:
        body_parts = args[2:attach_idx]
        attachments = args[attach_idx + 1:]
    else:
        body_parts = args[2:]
        attachments = []
    send(args[0], args[1], " ".join(body_parts), attachments)
