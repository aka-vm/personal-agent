#!/usr/bin/env python3
"""WhatsApp CLI via local Baileys bridge (http://localhost:3001)"""
import sys, json, os
import urllib.request
import urllib.error

BASE = "http://localhost:3001"


def req(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, method=method,
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())
    except Exception as e:
        return {"error": str(e)}


# ── contact resolution (Google + Apple, via contacts.py) ────────────────────────

def _resolve(name):
    """Return [{name, phone, source}] for contacts matching `name` that have a
    usable phone number. Fuzzy: 'prabhav' matches 'Prabhav Dogra'."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from contacts import google_search, apple_search
    results = google_search(name) + apple_search(name)
    out, seen = [], set()
    for c in results:
        nm = c.get("name", "")
        if nm.startswith("["):          # skip "[Google error: ...]" rows
            continue
        ph = "".join(ch for ch in (c.get("phone") or "") if ch.isdigit())
        if len(ph) < 10:                # not a real phone (e.g. WhatsApp LID)
            continue
        key = ph[-10:]
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": nm, "phone": ph, "source": c.get("source", "?")})
    return out


def cmd_resolve(name):
    matches = _resolve(name)
    if not matches:
        print(f"No contact with a phone number found for '{name}'.")
        return
    for m in matches:
        print(f"{m['name']}  +{m['phone']}  [{m['source']}]")


def cmd_text(name, message):
    """Resolve a name to a contact and send — the one-step way to text someone.
    Passes the resolved name so the history-group log shows it, not the number."""
    matches = _resolve(name)
    if not matches:
        print(f"No contact found for '{name}'. Provide a number or a closer name.")
        return
    if len(matches) > 1:
        print(f"Multiple matches for '{name}' — be more specific:")
        for m in matches:
            print(f"  {m['name']}  +{m['phone']}")
        return
    m = matches[0]
    r = req("POST", "/send", {"phone": m["phone"], "message": message, "name": m["name"]})
    print(f"Sent to {m['name']} (+{m['phone']})" if r.get("ok") else f"Error: {r.get('error')}")


# ── raw send (when you already have a number; pass name so the log is readable) ─

def cmd_send(phone, message, name=None):
    body = {"phone": phone, "message": message}
    if name:
        body["name"] = name
    r = req("POST", "/send", body)
    print("Sent" if r.get("ok") else f"Error: {r.get('error')}")


def cmd_send_group(group_id, message):
    r = req("POST", "/send-group", {"groupId": group_id, "message": message})
    print("Sent" if r.get("ok") else f"Error: {r.get('error')}")


def cmd_send_file(phone, file_path, caption=""):
    r = req("POST", "/send-file", {"phone": phone, "filePath": file_path, "caption": caption})
    print("Sent" if r.get("ok") else f"Error: {r.get('error')}")


def cmd_messages(limit=20, from_phone=None):
    path = f"/messages?limit={limit}"
    if from_phone:
        path += f"&from={from_phone}"
    msgs = req("GET", path)
    if isinstance(msgs, list):
        for m in msgs:
            direction = "→" if m.get("fromMe") else "←"
            print(f"[{m.get('timestamp','')}] {direction} {m.get('from','?')}: {m.get('text','')}")
    else:
        print(f"Error: {msgs.get('error')}")


def cmd_status():
    r = req("GET", "/status")
    if r.get("connected"):
        print(f"Connected as +{r['phone']}")
    elif r.get("qrReady"):
        print("Not connected — QR is ready. Run: wa.py qr")
    else:
        print("Not connected — QR not ready yet, starting up...")


def cmd_qr():
    r = req("GET", "/qr")
    if "error" in r:
        print(f"Already connected as +{r.get('phone','?')}" if r["error"] == "already_connected"
              else f"Error: {r['error']}")
        return
    if r.get("path"):
        print(f"SEND_FILE:{r['path']}")


def cmd_reset():
    r = req("DELETE", "/session")
    print(r.get("message") or r.get("error"))


USAGE = """Usage: wa.py <command> [args]

Messaging people (preferred):
  text <name> "<message>"      — resolve name via contacts, send, log with name
                                 fuzzy: `text prabhav "hi"` → Prabhav Dogra
  resolve <name>               — show matching contacts + numbers (no send)

Lower-level:
  send <phone> "<msg>" [name]  — send to a raw number (pass name for a clean log)
  send_group <groupId> "<msg>"
  send_file <phone> <path>
  messages [limit] [phone]     — recent received messages

Admin:
  status | qr | reset
"""

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(USAGE); sys.exit(0)
    c = args[0]
    if c == "text":               cmd_text(args[1], " ".join(args[2:]))
    elif c == "resolve":          cmd_resolve(" ".join(args[1:]))
    elif c == "send":             cmd_send(args[1], args[2] if len(args) > 2 else "",
                                           args[3] if len(args) > 3 else None)
    elif c == "send_group":       cmd_send_group(args[1], " ".join(args[2:]))
    elif c == "send_file":        cmd_send_file(args[1], args[2], " ".join(args[3:]))
    elif c == "status":           cmd_status()
    elif c == "qr":               cmd_qr()
    elif c == "messages":
        limit = int(args[1]) if len(args) > 1 and args[1].isdigit() else 20
        phone = args[2] if len(args) > 2 else None
        cmd_messages(limit, phone)
    elif c == "reset":            cmd_reset()
    else:
        print(f"Unknown command: {c}\n{USAGE}")
