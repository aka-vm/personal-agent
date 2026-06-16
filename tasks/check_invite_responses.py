#!/usr/bin/env python3
"""
One-time check: did Shaunak, Akshit, Ansh respond to their Catching up invites?
Sends Telegram notification for anyone who hasn't responded.
"""
import sys
import os
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.gcal import get_service
from core.config import config

EVENTS = [
    {"who": "Akshit Tyagi",  "email": "akshit.t@aftershoot.com",  "time": "2026-06-17T12:30:00+05:30"},
    {"who": "Shaunak Pal",   "email": "shaunak.p@aftershoot.com", "time": "2026-06-17T13:30:00+05:30"},
    {"who": "Ansh Jain",     "email": "ansh.j@aftershoot.com",    "time": "2026-06-18T12:00:00+05:30"},
]

def check_responses():
    svc = get_service("work")
    no_response = []

    for ev in EVENTS:
        result = svc.events().list(
            calendarId="primary",
            timeMin=ev["time"],
            timeMax=ev["time"].replace(":00+", ":01+"),
            q="Catching up",
            singleEvents=True,
        ).execute()

        for event in result.get("items", []):
            for attendee in event.get("attendees", []):
                if attendee["email"] == ev["email"]:
                    status = attendee.get("responseStatus", "needsAction")
                    if status == "needsAction":
                        no_response.append(ev["who"])

    return no_response

def send_telegram(text):
    token = config.secret("TELEGRAM_BOT_TOKEN")
    chat_id = config.get("telegram.allowed_id")
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=10,
    )

if __name__ == "__main__":
    no_response = check_responses()
    if no_response:
        names = ", ".join(no_response)
        send_telegram(f"Reminder: {names} haven't responded to the Catching up calendar invite yet.")
    else:
        send_telegram("All good — Shaunak, Akshit, and Ansh have all responded to their Catching up invites.")
