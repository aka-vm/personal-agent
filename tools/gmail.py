#!/usr/bin/env python3
"""
Gmail CLI — personal + work accounts
Usage:
  gmail.py list [personal|work] [limit]       — recent inbox emails
  gmail.py unread [personal|work] [limit]     — unread emails
  gmail.py search <personal|work> <query>     — search emails
  gmail.py read <personal|work> <msg_id>      — read full email
  gmail.py send <personal|work> <to> <subject> <body>
  gmail.py labels [personal|work]             — list labels
"""
import sys, os, base64, re
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from email.mime.text import MIMEText
from datetime import datetime

CONFIG_DIR = os.path.expanduser("~/.config/google")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from google_scopes import SCOPES

# Account = the token file basename under ~/.config/google/ (e.g. personal_token.json).
# No emails hardcoded — the sender address is read from the authenticated profile.
ACCOUNTS = ("personal", "work")

def get_service(account):
    token_file = os.path.join(CONFIG_DIR, f"{account}_token.json")
    if not os.path.exists(token_file):
        print(f"No token for {account}. Run: python3 google_auth.py {account}")
        sys.exit(1)
    creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        open(token_file, "w").write(creds.to_json())
    return build("gmail", "v1", credentials=creds)

def decode_body(payload):
    """Extract plain text body from message payload."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        result = decode_body(part)
        if result:
            return result
    return ""

def fmt_date(ts_ms):
    try:
        return datetime.fromtimestamp(int(ts_ms) / 1000).strftime("%d %b %Y, %I:%M %p")
    except:
        return str(ts_ms)

def header(headers, name):
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""

def fmt_msg(msg, svc):
    hdrs = msg["payload"]["headers"]
    subj = header(hdrs, "Subject") or "(no subject)"
    frm  = header(hdrs, "From")
    date = fmt_date(msg.get("internalDate", 0))
    unread = "UNREAD" in msg.get("labelIds", [])
    mark = "●" if unread else " "
    return f"  {mark} [{msg['id']}]  {date}  {frm[:30]:<30}  {subj[:60]}"

def cmd_list(account, limit=15, query="in:inbox"):
    svc = get_service(account)
    result = svc.users().messages().list(
        userId="me", q=query, maxResults=int(limit)
    ).execute()
    msgs = result.get("messages", [])
    print(f"\n── {account.upper()} Gmail ({len(msgs)} shown) ──")
    print(f"  {'●=unread':<10} {'ID':<10} {'Date':<22} {'From':<30} Subject")
    print(f"  {'-'*110}")
    for m in msgs:
        full = svc.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()
        print(fmt_msg(full, svc))

def cmd_unread(account, limit=15):
    cmd_list(account, limit, query="in:inbox is:unread")

def cmd_search(account, query, limit=15):
    svc = get_service(account)
    result = svc.users().messages().list(
        userId="me", q=query, maxResults=int(limit)
    ).execute()
    msgs = result.get("messages", [])
    print(f"\n── {account.upper()} Gmail — Search: '{query}' ({len(msgs)} results) ──")
    for m in msgs:
        full = svc.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()
        print(fmt_msg(full, svc))

def cmd_read(account, msg_id):
    svc = get_service(account)
    # Listings now print full IDs, so msg_id is normally used directly. Fallback:
    # if a short prefix was passed, resolve it from recent messages (search wider).
    if len(msg_id) < 16:
        match = None
        result = svc.users().messages().list(userId="me", maxResults=200).execute()
        for m in result.get("messages", []):
            if m["id"].startswith(msg_id):
                match = m["id"]; break
        if not match:
            print(f"Couldn't resolve short id '{msg_id}'. Use the full ID from the listing.")
            return
        msg_id = match
    try:
        msg = svc.users().messages().get(userId="me", id=msg_id, format="full").execute()
    except Exception as e:
        print(f"Couldn't open message {msg_id}: {e}")
        return
    hdrs = msg["payload"]["headers"]
    print(f"\nFrom:    {header(hdrs, 'From')}")
    print(f"To:      {header(hdrs, 'To')}")
    print(f"Subject: {header(hdrs, 'Subject')}")
    print(f"Date:    {fmt_date(msg.get('internalDate', 0))}")
    print(f"\n{'-'*60}")
    body = decode_body(msg["payload"]).strip()
    # trim quoted reply chains
    lines = body.split("\n")
    trimmed = []
    for line in lines:
        if line.startswith(">") or re.match(r"On .+ wrote:", line):
            break
        trimmed.append(line)
    print("\n".join(trimmed[:80]))
    if len(trimmed) > 80:
        print(f"\n... ({len(trimmed) - 80} more lines)")
    # mark as read
    svc.users().messages().modify(
        userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()

def cmd_send(account, to, subject, body):
    svc = get_service(account)
    from_addr = svc.users().getProfile(userId="me").execute().get("emailAddress", "me")
    mime = MIMEText(body)
    mime["To"] = to
    mime["From"] = from_addr
    mime["Subject"] = subject
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    svc.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"✓ Email sent to {to}")

def cmd_labels(account):
    svc = get_service(account)
    labels = svc.users().labels().list(userId="me").execute().get("labels", [])
    print(f"\n── {account.upper()} Labels ──")
    for l in sorted(labels, key=lambda x: x["name"]):
        print(f"  {l['name']:<35} {l['id']}")

def cmd_count(account, query):
    """Fast count of messages matching a Gmail query (one list call per 500)."""
    svc = get_service(account)
    total, token = 0, None
    while True:
        resp = svc.users().messages().list(
            userId="me", q=query, maxResults=500, pageToken=token
        ).execute()
        total += len(resp.get("messages", []))
        token = resp.get("nextPageToken")
        if not token or total >= 2000:
            break
    print(total)

def resolve_accounts(arg):
    if arg in ("personal", "work"):
        return [arg]
    return ["personal", "work"]

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__); sys.exit(0)

    cmd = args[0]

    if cmd == "list":
        account = args[1] if len(args) > 1 and args[1] in ACCOUNTS else "personal"
        limit   = args[2] if len(args) > 2 else 15
        cmd_list(account, limit)
    elif cmd == "unread":
        account = args[1] if len(args) > 1 and args[1] in ACCOUNTS else "personal"
        limit   = args[2] if len(args) > 2 else 15
        cmd_unread(account, limit)
    elif cmd == "count":
        cmd_count(args[1], " ".join(args[2:]))
    elif cmd == "search":
        cmd_search(args[1], " ".join(args[2:]))
    elif cmd == "read":
        cmd_read(args[1], args[2])
    elif cmd == "send":
        cmd_send(args[1], args[2], args[3], " ".join(args[4:]))
    elif cmd == "labels":
        account = args[1] if len(args) > 1 else "personal"
        cmd_labels(account)
    else:
        print(__doc__)
