#!/usr/bin/env python3
"""
Apple Contacts CLI via iCloud CardDAV
Usage:
  apple_contacts.py list [limit]
  apple_contacts.py search <query>
  apple_contacts.py add <name> <phone> [email]
"""
import sys, os, json, base64, uuid
import urllib.request, urllib.error
import xml.etree.ElementTree as ET
import vobject
from concurrent.futures import ThreadPoolExecutor, as_completed

CREDS_FILE = os.path.expanduser("~/.config/apple/creds.json")

def get_creds():
    return json.load(open(CREDS_FILE))

def auth_header(creds):
    token = base64.b64encode(f"{creds['apple_id']}:{creds['app_password']}".encode()).decode()
    return f"Basic {token}"

def propfind(url, body, creds, depth="0"):
    auth = auth_header(creds)
    req = urllib.request.Request(url, data=body, method="PROPFIND", headers={
        "Authorization": auth,
        "Content-Type": "text/xml; charset=utf-8",
        "Depth": depth,
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        return ET.fromstring(r.read())

def discover_addressbook_url(creds):
    # Step 1: find principal from root
    body1 = b"""<?xml version="1.0" encoding="UTF-8"?>
<propfind xmlns="DAV:"><prop><current-user-principal/></prop></propfind>"""
    root1 = propfind("https://contacts.icloud.com/", body1, creds, depth="0")
    href_el = root1.find(".//{DAV:}current-user-principal/{DAV:}href")
    if href_el is None:
        raise RuntimeError("Could not find principal href")
    principal_path = href_el.text  # e.g. /17532709930/principal/
    principal_url = f"https://contacts.icloud.com{principal_path}"

    # Step 2: find addressbook-home-set
    body2 = b"""<?xml version="1.0" encoding="UTF-8"?>
<propfind xmlns="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">
  <prop><card:addressbook-home-set/></prop>
</propfind>"""
    root2 = propfind(principal_url, body2, creds, depth="0")
    href2 = root2.find(".//{urn:ietf:params:xml:ns:carddav}addressbook-home-set/{DAV:}href")
    if href2 is None:
        raise RuntimeError("Could not find addressbook-home-set")
    home_url = href2.text.rstrip("/")  # full URL, e.g. https://p34-contacts.icloud.com:443/17532709930/carddavhome

    # Step 3: find the card/ addressbook collection
    body3 = b"""<?xml version="1.0" encoding="UTF-8"?>
<propfind xmlns="DAV:"><prop><resourcetype/></prop></propfind>"""
    root3 = propfind(home_url + "/", body3, creds, depth="1")
    for resp in root3.findall("{DAV:}response"):
        rt = resp.find(".//{urn:ietf:params:xml:ns:carddav}addressbook")
        if rt is not None:
            href_el = resp.find("{DAV:}href")
            if href_el is not None:
                path = href_el.text
                # path may be relative or absolute
                if path.startswith("http"):
                    return path.rstrip("/")
                return home_url.rsplit("/", home_url.count("/") - 2)[0] + path.rstrip("/")
    return home_url + "/card"

def fetch_vcard_hrefs(ab_url, creds):
    body = b"""<?xml version="1.0" encoding="UTF-8"?>
<propfind xmlns="DAV:"><prop><getetag/></prop></propfind>"""
    root = propfind(ab_url + "/", body, creds, depth="1")
    hrefs = []
    for resp in root.findall(".//{DAV:}response"):
        href_el = resp.find("{DAV:}href")
        if href_el is not None and href_el.text and href_el.text.endswith(".vcf"):
            hrefs.append(href_el.text)
    return hrefs

def get_base_url(ab_url):
    from urllib.parse import urlparse
    p = urlparse(ab_url)
    port = f":{p.port}" if p.port and p.port not in (80, 443) else ""
    return f"{p.scheme}://{p.hostname}{port}"

def fetch_vcard(href, ab_url, creds):
    auth = auth_header(creds)
    base = get_base_url(ab_url)
    url = href if href.startswith("http") else base + href
    req = urllib.request.Request(url, headers={"Authorization": auth})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read().decode("utf-8", errors="replace")
        return vobject.readOne(data)
    except Exception:
        return None

def fetch_all_contacts(creds, ab_url, max_workers=10):
    hrefs = fetch_vcard_hrefs(ab_url, creds)
    contacts = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_vcard, h, ab_url, creds): h for h in hrefs}
        for fut in as_completed(futures):
            vc = fut.result()
            if vc:
                contacts.append(vc)
    return contacts

def fmt_contact(vcard):
    name = str(getattr(vcard, "fn", None) and vcard.fn.value or "(no name)")
    phones = []
    if hasattr(vcard, "tel"):
        tels = vcard.tel if isinstance(vcard.tel, list) else [vcard.tel]
        phones = [str(t.value) for t in tels]
    emails = []
    if hasattr(vcard, "email"):
        ems = vcard.email if isinstance(vcard.email, list) else [vcard.email]
        emails = [str(e.value) for e in ems]
    phone_str = phones[0] if phones else ""
    email_str = emails[0] if emails else ""
    return f"{name:<35} {phone_str:<20} {email_str}"

def cmd_list(limit=50):
    creds = get_creds()
    ab_url = discover_addressbook_url(creds)
    contacts = fetch_all_contacts(creds, ab_url)
    contacts.sort(key=lambda v: str(getattr(v, "fn", None) and v.fn.value or "").lower())
    print(f"\n── Apple Contacts ({len(contacts)} total, showing {min(limit, len(contacts))}) ──")
    for vc in contacts[:limit]:
        print(f"  {fmt_contact(vc)}")

def cmd_search(query):
    creds = get_creds()
    ab_url = discover_addressbook_url(creds)
    contacts = fetch_all_contacts(creds, ab_url)
    q = query.lower()
    results = []
    for vc in contacts:
        name = str(getattr(vc, "fn", None) and vc.fn.value or "").lower()
        phones = []
        if hasattr(vc, "tel"):
            tels = vc.tel if isinstance(vc.tel, list) else [vc.tel]
            phones = [str(t.value).lower() for t in tels]
        if q in name or any(q in p for p in phones):
            results.append(vc)
    print(f"\n── Apple Contacts — Search: '{query}' ──")
    if not results:
        print("  No results.")
    for vc in results:
        print(f"  {fmt_contact(vc)}")

def cmd_add(name, phone, email=""):
    creds = get_creds()
    ab_url = discover_addressbook_url(creds)
    uid = str(uuid.uuid4()).upper()
    vcard = f"BEGIN:VCARD\r\nVERSION:3.0\r\nUID:{uid}\r\nFN:{name}\r\nN:{name};;;;\r\nTEL;type=CELL:{phone}\r\n"
    if email:
        vcard += f"EMAIL;type=INTERNET:{email}\r\n"
    vcard += "END:VCARD"

    base = get_base_url(ab_url)
    url = f"{ab_url}/{uid}.vcf"
    auth = auth_header(creds)
    req = urllib.request.Request(url, data=vcard.encode(), method="PUT", headers={
        "Authorization": auth,
        "Content-Type": "text/vcard; charset=utf-8",
    })
    with urllib.request.urlopen(req, timeout=10):
        pass
    print(f"✓ Contact added: {name}")

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "list":
        limit = int(args[1]) if len(args) > 1 else 50
        cmd_list(limit)
    elif args[0] == "search":
        cmd_search(" ".join(args[1:]))
    elif args[0] == "add":
        email = args[3] if len(args) > 3 else ""
        cmd_add(args[1], args[2], email)
    else:
        print(__doc__)
