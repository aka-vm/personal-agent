#!/usr/bin/env python3
"""
Google Calendar CLI — personal + work accounts
Usage:
  gcal.py list [personal|work|both] [days]
  gcal.py today [personal|work|both]
  gcal.py week [personal|work|both]
  gcal.py add <account> <title> <date> [time] [duration_mins] [description]
  gcal.py search <account> <query>
  gcal.py calendars [personal|work|both]
"""
import sys, os, json
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

CONFIG_DIR = os.path.expanduser("~/.config/google")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from google_scopes import SCOPES

def get_service(account):
    token_file = os.path.join(CONFIG_DIR, f"{account}_token.json")
    if not os.path.exists(token_file):
        print(f"No token for {account}. Run: python3 google_auth.py {account}")
        sys.exit(1)
    creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_file, "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)

RSVP_EMOJI = {"accepted": "✅", "tentative": "🤔", "declined": "❌", "needsAction": "❔"}


def rsvp_status(event):
    """The user's own RSVP on this event: accepted/tentative/declined/needsAction,
    or None for solo/own events with no invitee status."""
    for a in event.get("attendees", []):
        if a.get("self"):
            return a.get("responseStatus")
    return None


def format_event(event, account_label=""):
    start = event["start"].get("dateTime", event["start"].get("date", ""))
    end   = event["end"].get("dateTime", event["end"].get("date", ""))
    title = event.get("summary", "(no title)")
    loc   = event.get("location", "")
    label = f"[{account_label}] " if account_label else ""

    try:
        dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone()
        et = datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone()
        time_str = f"{dt.strftime('%a %d %b, %I:%M %p')} – {et.strftime('%I:%M %p')}"
    except:
        time_str = start

    emoji = RSVP_EMOJI.get(rsvp_status(event), "")
    prefix = f"{emoji} " if emoji else ""
    line = f"{prefix}{label}{time_str}  |  {title}"
    if loc:
        line += f"\n    📍 {loc}"
    link = event.get("htmlLink", "")
    if link:
        line += f"\n    🔗 {link}"
    return line

def get_events(service, days_ahead=7, days_back=0):
    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=days_back)).isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()
    result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        maxResults=50,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return result.get("items", [])

def cmd_list(accounts, days=7):
    for account in accounts:
        svc = get_service(account)
        events = get_events(svc, days_ahead=int(days))
        print(f"\n── {account.upper()} ({days} days) ──")
        if not events:
            print("  No events.")
        for e in events:
            print(f"  {format_event(e)}")

def fetch_today(account):
    """Return today's events (local-day) for one account as raw API items."""
    svc = get_service(account)
    # "Today" must be in LOCAL time, not UTC — at 01:00 IST, UTC is still
    # yesterday, which would show the wrong day's events.
    now = datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    result = svc.events().list(
        calendarId="primary",
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return result.get("items", [])

def cmd_json_today(accounts):
    """Structured today's events as JSON — for the briefing and other consumers."""
    import json as _json
    out = []
    for account in accounts:
        for e in fetch_today(account):
            s, en = e["start"], e["end"]
            all_day = "date" in s and "dateTime" not in s
            out.append({
                "account": account,
                "summary": e.get("summary", "(no title)"),
                "start": s.get("dateTime", s.get("date")),
                "end": en.get("dateTime", en.get("date")),
                "all_day": all_day,
                "location": e.get("location", ""),
                "link": e.get("htmlLink", ""),
                "rsvp": rsvp_status(e),
            })
    print(_json.dumps(out))

def cmd_today(accounts):
    for account in accounts:
        events = fetch_today(account)
        print(f"\n── {account.upper()} — TODAY ──")
        if not events:
            print("  Nothing today.")
        for e in events:
            print(f"  {format_event(e)}")

def cmd_week(accounts):
    cmd_list(accounts, days=7)

def cmd_add(account, title, date_str, time_str=None, duration=60, description="", end_date_str=None):
    svc = get_service(account)
    if time_str:
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        end_dt   = start_dt + timedelta(minutes=int(duration))
        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Kolkata"},
            "end":   {"dateTime": end_dt.isoformat(),   "timeZone": "Asia/Kolkata"},
        }
    else:
        # all-day: end date is exclusive, so add 1 day for single-day events
        if end_date_str:
            end_d = datetime.strptime(end_date_str, "%Y-%m-%d") + timedelta(days=1)
        else:
            end_d = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
        event = {
            "summary": title,
            "description": description,
            "start": {"date": date_str},
            "end":   {"date": end_d.strftime("%Y-%m-%d")},
        }
    created = svc.events().insert(calendarId="primary", body=event).execute()
    print(f"✓ Created: {created.get('summary')} ({created.get('htmlLink')})")

def cmd_search(account, query):
    svc = get_service(account)
    result = svc.events().list(
        calendarId="primary",
        q=query,
        maxResults=20,
        singleEvents=True,
        orderBy="startTime",
        timeMin=datetime.now(timezone.utc).isoformat(),
    ).execute()
    events = result.get("items", [])
    print(f"\n── {account.upper()} — Search: '{query}' ──")
    if not events:
        print("  No results.")
    for e in events:
        print(f"  {format_event(e)}")

def cmd_calendars(accounts):
    for account in accounts:
        svc = get_service(account)
        result = svc.calendarList().list().execute()
        print(f"\n── {account.upper()} calendars ──")
        for cal in result.get("items", []):
            print(f"  {cal['summary']} ({cal['id']})")

def resolve_accounts(arg):
    if arg == "both":
        return ["personal", "work"]
    if arg in ("personal", "work"):
        return [arg]
    return ["personal"]  # default

USAGE = """Usage:
  gcal.py list [personal|work|both] [days=7]
  gcal.py today [personal|work|both]
  gcal.py week [personal|work|both]
  gcal.py add <personal|work> <title> <YYYY-MM-DD> [end_date|HH:MM] [duration_mins] [description]
  gcal.py search <personal|work> <query>
  gcal.py calendars [personal|work|both]
"""

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(USAGE); sys.exit(0)

    cmd = args[0]

    if cmd == "list":
        accounts = resolve_accounts(args[1] if len(args) > 1 else "both")
        days = args[2] if len(args) > 2 else 7
        cmd_list(accounts, days)

    elif cmd == "json-today":
        accounts = resolve_accounts(args[1] if len(args) > 1 else "both")
        cmd_json_today(accounts)

    elif cmd == "today":
        accounts = resolve_accounts(args[1] if len(args) > 1 else "both")
        cmd_today(accounts)

    elif cmd == "week":
        accounts = resolve_accounts(args[1] if len(args) > 1 else "both")
        cmd_week(accounts)

    elif cmd == "add":
        if len(args) < 4:
            print("Usage: gcal.py add <account> <title> <YYYY-MM-DD> [HH:MM] [duration_mins] [description]")
            sys.exit(1)
        account  = args[1]
        title    = args[2]
        date_str = args[3]
        # detect if arg[4] is an end date (YYYY-MM-DD) or a time (HH:MM)
        arg4 = args[4] if len(args) > 4 else None
        if arg4 and len(arg4) == 10 and arg4[4] == "-":
            end_date_str = arg4
            time_str     = None
            duration     = args[5] if len(args) > 5 else 60
            description  = args[6] if len(args) > 6 else ""
        else:
            end_date_str = None
            time_str     = arg4
            duration     = args[5] if len(args) > 5 else 60
            description  = args[6] if len(args) > 6 else ""
        cmd_add(account, title, date_str, time_str, duration, description, end_date_str)

    elif cmd == "search":
        account = args[1] if len(args) > 1 else "personal"
        query   = " ".join(args[2:]) if len(args) > 2 else ""
        cmd_search(account, query)

    elif cmd == "calendars":
        accounts = resolve_accounts(args[1] if len(args) > 1 else "both")
        cmd_calendars(accounts)

    else:
        print(f"Unknown command: {cmd}\n{USAGE}")
