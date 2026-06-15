#!/usr/bin/env python3
"""
Google Contacts CLI — personal + work accounts
Usage:
  gcontacts.py list [personal|work] [limit]
  gcontacts.py search <personal|work> <query>
  gcontacts.py get <personal|work> <resourceName>
  gcontacts.py add <personal|work> <name> <phone> [email]
"""
import sys, os
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
    return build("people", "v1", credentials=creds)

def fmt_contact(p):
    names  = p.get("names", [{}])
    phones = p.get("phoneNumbers", [{}])
    emails = p.get("emailAddresses", [{}])
    name   = names[0].get("displayName", "(no name)") if names else "(no name)"
    phone  = phones[0].get("value", "") if phones else ""
    email  = emails[0].get("value", "") if emails else ""
    rid    = p.get("resourceName", "")
    return f"{name:<35} {phone:<20} {email:<30} {rid}"

def cmd_list(account, limit=50):
    svc = get_service(account)
    result = svc.people().connections().list(
        resourceName="people/me",
        pageSize=int(limit),
        personFields="names,phoneNumbers,emailAddresses",
        sortOrder="FIRST_NAME_ASCENDING",
    ).execute()
    contacts = result.get("connections", [])
    print(f"\n── {account.upper()} Contacts ({len(contacts)} shown) ──")
    print(f"  {'Name':<35} {'Phone':<20} {'Email':<30} Resource")
    print(f"  {'-'*110}")
    for p in contacts:
        print(f"  {fmt_contact(p)}")

def cmd_search(account, query):
    svc = get_service(account)
    result = svc.people().searchContacts(
        query=query,
        readMask="names,phoneNumbers,emailAddresses",
    ).execute()
    contacts = [r.get("person", {}) for r in result.get("results", [])]
    print(f"\n── {account.upper()} — Search: '{query}' ──")
    if not contacts:
        print("  No results.")
    for p in contacts:
        print(f"  {fmt_contact(p)}")

def cmd_get(account, resource_name):
    svc = get_service(account)
    p = svc.people().get(
        resourceName=resource_name,
        personFields="names,phoneNumbers,emailAddresses,organizations,biographies,addresses",
    ).execute()
    names  = p.get("names", [{}])
    phones = p.get("phoneNumbers", [])
    emails = p.get("emailAddresses", [])
    orgs   = p.get("organizations", [])
    print(f"\nName:  {names[0].get('displayName','') if names else ''}")
    for ph in phones:
        print(f"Phone: {ph.get('value','')} ({ph.get('type','')})")
    for em in emails:
        print(f"Email: {em.get('value','')} ({em.get('type','')})")
    for org in orgs:
        print(f"Org:   {org.get('name','')} — {org.get('title','')}")

def cmd_add(account, name, phone, email=""):
    svc = get_service(account)
    body = {
        "names": [{"givenName": name}],
        "phoneNumbers": [{"value": phone, "type": "mobile"}],
    }
    if email:
        body["emailAddresses"] = [{"value": email, "type": "home"}]
    p = svc.people().createContact(body=body).execute()
    display = p.get("names", [{}])[0].get("displayName", name)
    print(f"✓ Contact created: {display} ({p.get('resourceName','')})")

USAGE = __doc__

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args: print(USAGE); sys.exit(0)
    cmd = args[0]

    if cmd == "list":
        account = args[1] if len(args) > 1 else "personal"
        limit   = args[2] if len(args) > 2 else 50
        cmd_list(account, limit)
    elif cmd == "search":
        cmd_search(args[1], " ".join(args[2:]))
    elif cmd == "get":
        cmd_get(args[1], args[2])
    elif cmd == "add":
        email = args[4] if len(args) > 4 else ""
        cmd_add(args[1], args[2], args[3], email)
    else:
        print(f"Unknown: {cmd}\n{USAGE}")
