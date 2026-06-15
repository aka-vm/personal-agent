#!/usr/bin/env python3
"""
Unified Contacts — searches Google (personal) + Apple iCloud
Usage:
  contacts.py search <query>
  contacts.py list [limit]
"""
import sys, os, json, base64, uuid
import urllib.request, urllib.error
import xml.etree.ElementTree as ET
import vobject
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Google ────────────────────────────────────────────────────────────────────

def google_search(query):
    try:
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from google_scopes import SCOPES
        token_file = os.path.expanduser("~/.config/google/personal_token.json")
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            open(token_file, "w").write(creds.to_json())
        svc = build("people", "v1", credentials=creds)
        result = svc.people().searchContacts(
            query=query,
            readMask="names,phoneNumbers,emailAddresses",
        ).execute()
        contacts = []
        for r in result.get("results", []):
            p = r.get("person", {})
            name  = (p.get("names") or [{}])[0].get("displayName", "(no name)")
            phone = (p.get("phoneNumbers") or [{}])[0].get("value", "")
            email = (p.get("emailAddresses") or [{}])[0].get("value", "")
            contacts.append({"name": name, "phone": phone, "email": email, "source": "Google"})
        return contacts
    except Exception as e:
        return [{"name": f"[Google error: {e}]", "phone": "", "email": "", "source": "Google"}]

# ── Apple ─────────────────────────────────────────────────────────────────────

def _auth(creds):
    token = base64.b64encode(f"{creds['apple_id']}:{creds['app_password']}".encode()).decode()
    return f"Basic {token}"

def _propfind(url, body, auth, depth="0"):
    req = urllib.request.Request(url, data=body, method="PROPFIND", headers={
        "Authorization": auth, "Content-Type": "text/xml; charset=utf-8", "Depth": depth,
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        return ET.fromstring(r.read())

def _discover_ab(creds):
    auth = _auth(creds)
    root1 = _propfind("https://contacts.icloud.com/",
        b"""<?xml version="1.0" encoding="UTF-8"?><propfind xmlns="DAV:"><prop><current-user-principal/></prop></propfind>""",
        auth)
    principal_path = root1.find(".//{DAV:}current-user-principal/{DAV:}href").text
    principal_url = f"https://contacts.icloud.com{principal_path}"

    root2 = _propfind(principal_url,
        b"""<?xml version="1.0" encoding="UTF-8"?><propfind xmlns="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav"><prop><card:addressbook-home-set/></prop></propfind>""",
        auth)
    home_url = root2.find(".//{urn:ietf:params:xml:ns:carddav}addressbook-home-set/{DAV:}href").text.rstrip("/")

    root3 = _propfind(home_url + "/",
        b"""<?xml version="1.0" encoding="UTF-8"?><propfind xmlns="DAV:"><prop><resourcetype/></prop></propfind>""",
        auth, depth="1")
    for resp in root3.findall("{DAV:}response"):
        if resp.find(".//{urn:ietf:params:xml:ns:carddav}addressbook") is not None:
            href_el = resp.find("{DAV:}href")
            if href_el is not None:
                path = href_el.text
                if path.startswith("http"):
                    return path.rstrip("/")
                from urllib.parse import urlparse
                p = urlparse(home_url)
                base = f"{p.scheme}://{p.hostname}{':' + str(p.port) if p.port else ''}"
                return base + path.rstrip("/")
    return home_url + "/card"

def _fetch_vcf(href, ab_url, auth):
    from urllib.parse import urlparse
    p = urlparse(ab_url)
    base = f"{p.scheme}://{p.hostname}{':' + str(p.port) if p.port else ''}"
    url = href if href.startswith("http") else base + href
    req = urllib.request.Request(url, headers={"Authorization": auth})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return vobject.readOne(r.read().decode("utf-8", errors="replace"))
    except Exception:
        return None

def apple_all():
    try:
        creds = json.load(open(os.path.expanduser("~/.config/apple/creds.json")))
        auth  = _auth(creds)
        ab_url = _discover_ab(creds)

        root = _propfind(ab_url + "/",
            b"""<?xml version="1.0" encoding="UTF-8"?><propfind xmlns="DAV:"><prop><getetag/></prop></propfind>""",
            auth, depth="1")
        hrefs = [resp.find("{DAV:}href").text
                 for resp in root.findall(".//{DAV:}response")
                 if resp.find("{DAV:}href") is not None and (resp.find("{DAV:}href").text or "").endswith(".vcf")]

        contacts = []
        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = {ex.submit(_fetch_vcf, h, ab_url, auth): h for h in hrefs}
            for fut in as_completed(futs):
                vc = fut.result()
                if vc:
                    name  = str(vc.fn.value) if hasattr(vc, "fn") else "(no name)"
                    phones = []
                    if hasattr(vc, "tel"):
                        tels = vc.tel if isinstance(vc.tel, list) else [vc.tel]
                        phones = [str(t.value) for t in tels]
                    emails = []
                    if hasattr(vc, "email"):
                        ems = vc.email if isinstance(vc.email, list) else [vc.email]
                        emails = [str(e.value) for e in ems]
                    contacts.append({
                        "name": name,
                        "phone": phones[0] if phones else "",
                        "email": emails[0] if emails else "",
                        "source": "Apple",
                    })
        return contacts
    except Exception as e:
        return [{"name": f"[Apple error: {e}]", "phone": "", "email": "", "source": "Apple"}]

def apple_search(query):
    q = query.lower()
    results = []
    for c in apple_all():
        if q in c["name"].lower() or q in c["phone"].lower():
            results.append(c)
    return results

# ── Unified ───────────────────────────────────────────────────────────────────

def fmt(c):
    src   = f"[{c['source']}]"
    name  = c["name"]
    phone = c["phone"]
    email = c["email"]
    return f"  {src:<8} {name:<35} {phone:<22} {email}"

def cmd_search(query):
    with ThreadPoolExecutor(max_workers=2) as ex:
        gf = ex.submit(google_search, query)
        af = ex.submit(apple_search, query)
        g_results = gf.result()
        a_results = af.result()

    # deduplicate by normalised phone
    def norm(p): return "".join(c for c in p if c.isdigit())[-10:]
    seen = set()
    combined = []
    for c in g_results + a_results:
        key = norm(c["phone"]) if c["phone"] else c["name"].lower()
        if key not in seen:
            seen.add(key)
            combined.append(c)

    print(f"\n── Contacts — '{query}' ({len(combined)} result{'s' if len(combined)!=1 else ''}) ──")
    if not combined:
        print("  No results.")
        return
    for c in combined:
        print(fmt(c))

def cmd_list(limit=30):
    with ThreadPoolExecutor(max_workers=2) as ex:
        af = ex.submit(apple_all)
        # For Google list, use search with empty-ish approach — just show apple + note
        a_results = af.result()

    a_results.sort(key=lambda c: c["name"].lower())
    print(f"\n── Apple Contacts ({len(a_results)} total, showing {min(limit, len(a_results))}) ──")
    for c in a_results[:limit]:
        print(fmt(c))
    print(f"\n(Google has 547+ contacts — use: contacts.py search <name>)")

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "list":
        limit = int(args[1]) if len(args) > 1 else 30
        cmd_list(limit)
    elif args[0] == "search":
        cmd_search(" ".join(args[1:]))
    else:
        print(__doc__)
