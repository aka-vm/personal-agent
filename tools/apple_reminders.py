#!/usr/bin/env python3
"""
Apple Reminders CLI via iCloud CalDAV
Usage:
  apple_reminders.py list [all]
  apple_reminders.py add <title> [list_name] [due_date YYYY-MM-DD]
  apple_reminders.py done <title_substring>
  apple_reminders.py lists
"""
import sys, os, json
import caldav
from datetime import datetime, date, timezone

CREDS_FILE = os.path.expanduser("~/.config/apple/creds.json")

def get_client():
    creds = json.load(open(CREDS_FILE))
    return caldav.DAVClient(
        url="https://caldav.icloud.com",
        username=creds["apple_id"],
        password=creds["app_password"],
    )

def get_todo_calendars(principal):
    return [c for c in principal.calendars()
            if "VTODO" in (c.get_supported_components() or [])]

def fmt_todo(todo):
    vtodo = todo.icalendar_component
    title = str(vtodo.get("SUMMARY", "(no title)"))
    due   = vtodo.get("DUE", None)
    prio  = vtodo.get("PRIORITY", None)
    done  = str(vtodo.get("STATUS", "")) == "COMPLETED"
    status = "✓" if done else "○"
    due_str = ""
    if due:
        try:
            d = due.dt
            if isinstance(d, datetime): d = d.date()
            due_str = f" — due {d}"
        except: pass
    return f"  {status} {title}{due_str}"

def cal_name(cal):
    try:
        return cal.get_display_name()
    except Exception:
        return str(cal)

def cmd_list(show_all=False):
    client = get_client()
    principal = client.principal()
    calendars = get_todo_calendars(principal)
    if not calendars:
        print("No reminder lists found.")
        return
    for cal in calendars:
        name = cal_name(cal)
        try:
            todos = cal.todos(include_completed=show_all)
        except:
            todos = []
        if not todos: continue
        print(f"\n── {cal_name(cal)} ──")
        for todo in todos:
            print(fmt_todo(todo))

def cmd_lists():
    client = get_client()
    principal = client.principal()
    calendars = get_todo_calendars(principal)
    print("\nReminder lists:")
    for cal in calendars:
        print(f"  • {cal_name(cal)}")

def cmd_add(title, list_name=None, due_date=None):
    client = get_client()
    principal = client.principal()
    calendars = get_todo_calendars(principal)
    if not calendars:
        print("No reminder lists found."); return

    cal = calendars[0]
    if list_name:
        for c in calendars:
            if list_name.lower() in cal_name(c).lower():
                cal = c; break

    due_str = ""
    if due_date:
        due_str = f"\nDUE;VALUE=DATE:{due_date.replace('-','')}"

    ical = f"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
SUMMARY:{title}{due_str}
STATUS:NEEDS-ACTION
END:VTODO
END:VCALENDAR"""
    cal.add_todo(ical)
    print(f"✓ Added to '{cal.name}': {title}")

def cmd_done(substring):
    client = get_client()
    principal = client.principal()
    calendars = get_todo_calendars(principal)
    found = False
    for cal in calendars:
        for todo in cal.todos():
            vtodo = todo.icalendar_component
            title = str(vtodo.get("SUMMARY", ""))
            if substring.lower() in title.lower():
                vtodo["STATUS"] = "COMPLETED"
                vtodo["COMPLETED"] = datetime.now(timezone.utc)
                todo.save()
                print(f"✓ Marked done: {title}")
                found = True
    if not found:
        print(f"No reminder matching '{substring}' found.")

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "list":
        show_all = len(args) > 1 and args[1] == "all"
        cmd_list(show_all)
    elif args[0] == "lists":
        cmd_lists()
    elif args[0] == "add":
        title     = args[1] if len(args) > 1 else ""
        list_name = args[2] if len(args) > 2 else None
        due_date  = args[3] if len(args) > 3 else None
        cmd_add(title, list_name, due_date)
    elif args[0] == "done":
        cmd_done(" ".join(args[1:]))
    else:
        print(__doc__)
