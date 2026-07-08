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
  gcal.py freebusy <name_or_email> [YYYY-MM-DD]
"""
import sys, os, json
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

IST = timezone(timedelta(hours=5, minutes=30))

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

def _resolve_work_email(name_or_email):
    """Resolve a name → email. Returns (email, display_name).
    Strategy: directory API → Gmail sent search → domain guess."""
    if '@' in name_or_email:
        display = name_or_email.split('@')[0].replace('.', ' ').title()
        return name_or_email, display

    # 1. Try Workspace directory API (requires directory.readonly scope; may 403)
    try:
        token_file = os.path.join(CONFIG_DIR, "work_token.json")
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        people_svc = build('people', 'v1', credentials=creds)
        res = people_svc.people().searchDirectoryPeople(
            query=name_or_email,
            readMask='emailAddresses,names',
            sources=['DIRECTORY_SOURCE_TYPE_DOMAIN_CONTACT'],
            pageSize=5,
        ).execute()
        people = res.get('people', [])
        if people:
            p = people[0]
            email = p.get('emailAddresses', [{}])[0].get('value', '')
            display = p.get('names', [{}])[0].get('displayName', name_or_email)
            if email:
                return email, display
    except Exception:
        pass

    # 2. Search Gmail for messages from/to this person to extract their email
    try:
        from googleapiclient.discovery import build as _build
        token_file = os.path.join(CONFIG_DIR, "work_token.json")
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        gmail_svc = _build('gmail', 'v1', credentials=creds)
        results = gmail_svc.users().messages().list(
            userId='me',
            q=f'from:{name_or_email}',
            maxResults=3,
        ).execute()
        msgs = results.get('messages', [])
        if msgs:
            msg = gmail_svc.users().messages().get(
                userId='me', id=msgs[0]['id'], format='metadata',
                metadataHeaders=['From'],
            ).execute()
            headers = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
            from_hdr = headers.get('From', '')
            # Parse "Display Name <email@domain.com>"
            import re
            m = re.search(r'<([^>]+)>', from_hdr)
            if m:
                email = m.group(1)
                display = from_hdr.split('<')[0].strip().strip('"') or name_or_email.title()
                return email, display
    except Exception:
        pass

    # 3. Fallback: guess aftershoot.com domain
    guess = f"{name_or_email.lower().replace(' ', '.')}@aftershoot.com"
    return guess, name_or_email.title()

def cmd_freebusy(name_or_email, date_str=None):
    """Check a co-worker's schedule. Tries event details first, falls back to free/busy blocks."""
    svc = get_service('work')
    email, display = _resolve_work_email(name_or_email)

    if date_str:
        target = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=IST)
    else:
        now = datetime.now(IST)
        target = now.replace(hour=0, minute=0, second=0, microsecond=0)

    day_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end   = day_start + timedelta(days=1)
    date_label = day_start.strftime('%A %d %b %Y')

    print(f"\n── {display} ({email}) — {date_label} ──")

    # Try full event listing first (works if calendar is shared or Workspace allows visibility)
    try:
        result = svc.events().list(
            calendarId=email,
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy='startTime',
        ).execute()
        events = result.get('items', [])
        if not events:
            print("  Nothing scheduled.")
        else:
            print("  (calendar shared — showing full details)")
            for e in events:
                print(f"  {format_event(e)}")
        return
    except Exception:
        pass

    # Fall back to free/busy query
    fb = svc.freebusy().query(body={
        'timeMin': day_start.isoformat(),
        'timeMax': day_end.isoformat(),
        'timeZone': 'Asia/Kolkata',
        'items': [{'id': email}],
    }).execute()
    busy = fb.get('calendars', {}).get(email, {}).get('busy', [])
    errors = fb.get('calendars', {}).get(email, {}).get('errors', [])

    if errors:
        print(f"  ⚠️  Can't read calendar: {errors[0].get('reason', 'unknown error')}")
        print(f"  (Try sharing their calendar with you, or ask them directly.)")
        return

    if not busy:
        print("  All free — no busy blocks found.")
        return

    print(f"  Busy ({len(busy)} block{'s' if len(busy) != 1 else ''}):")
    for slot in busy:
        s = datetime.fromisoformat(slot['start'].replace('Z', '+00:00')).astimezone(IST)
        e = datetime.fromisoformat(slot['end'].replace('Z', '+00:00')).astimezone(IST)
        print(f"  🔴 {s.strftime('%I:%M %p')} – {e.strftime('%I:%M %p')} IST")

    # Compute free windows between 9 AM and 7 PM
    work_start = day_start.replace(hour=9, minute=0)
    work_end   = day_start.replace(hour=19, minute=0)
    free = []
    cursor = work_start
    for slot in busy:
        s = datetime.fromisoformat(slot['start'].replace('Z', '+00:00')).astimezone(IST)
        e = datetime.fromisoformat(slot['end'].replace('Z', '+00:00')).astimezone(IST)
        s = max(s, work_start)
        if s > cursor:
            free.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < work_end:
        free.append((cursor, work_end))

    if free:
        print(f"\n  Free windows (9 AM–7 PM):")
        for fs, fe in free:
            dur = int((fe - fs).total_seconds() / 60)
            if dur >= 15:
                print(f"  🟢 {fs.strftime('%I:%M %p')} – {fe.strftime('%I:%M %p')} ({dur} min)")

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
  gcal.py freebusy <name_or_email> [YYYY-MM-DD]
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

    elif cmd == "freebusy":
        if len(args) < 2:
            print("Usage: gcal.py freebusy <name_or_email> [YYYY-MM-DD]")
            sys.exit(1)
        name_or_email = args[1]
        date_str = args[2] if len(args) > 2 else None
        cmd_freebusy(name_or_email, date_str)

    else:
        print(f"Unknown command: {cmd}\n{USAGE}")
