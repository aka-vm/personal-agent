#!/usr/bin/env python3
"""
Karakeep — save links / notes to Vineet's read-later (bookmarks) app.
Karakeep auto-fetches the page and AI-tags it after you add the URL.

Reads KARAKEEP_API_KEY from ~/.config/agent/secrets.env (generate one in
Karakeep → Settings → API Keys).

Usage:
  karakeep.py add <url> [note]      — save a link (optional note)
  karakeep.py note "<text>"         — save a text note
  karakeep.py search "<query>"      — search saved bookmarks
"""
import sys, os, json, urllib.request, urllib.error
from dotenv import dotenv_values

BASE = "http://localhost:3000/api/v1"
SECRETS = os.path.expanduser("~/.config/agent/secrets.env")


def _key():
    k = (dotenv_values(SECRETS).get("KARAKEEP_API_KEY")
         if os.path.exists(SECRETS) else None) or os.environ.get("KARAKEEP_API_KEY")
    if not k:
        print("No KARAKEEP_API_KEY in ~/.config/agent/secrets.env "
              "(generate one in Karakeep → Settings → API Keys).")
        sys.exit(1)
    return k


def _req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={
        "Authorization": f"Bearer {_key()}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def cmd_add(url, note="", tags=None):
    body = {"type": "link", "url": url}
    if note:
        body["note"] = note
    r = _req("POST", "/bookmarks", body)
    if r.get("error"):
        print(f"Error: {r['error']}"); return
    bid = r.get("id", "?")
    if tags:
        _req("POST", f"/bookmarks/{bid}/tags", {"tags": [{"tagName": t} for t in tags]})
    print(f"✓ Saved to Karakeep: {url}  (id {bid})" + (f"  tags: {', '.join(tags)}" if tags else ""))


def cmd_tag(bookmark_id, tags):
    r = _req("POST", f"/bookmarks/{bookmark_id}/tags", {"tags": [{"tagName": t} for t in tags]})
    print(f"✓ Tagged {bookmark_id}: {', '.join(tags)}" if not r.get("error") else f"Error: {r['error']}")


def cmd_note(text):
    r = _req("POST", "/bookmarks", {"type": "text", "text": text})
    print("✓ Note saved to Karakeep" if not r.get("error") else f"Error: {r['error']}")


def cmd_search(query):
    import urllib.parse
    r = _req("GET", f"/bookmarks/search?q={urllib.parse.quote(query)}")
    if r.get("error"):
        print(f"Error: {r['error']}"); return
    items = r.get("bookmarks", r.get("items", []))
    print(f"\n── Karakeep — '{query}' ({len(items)}) ──")
    for b in items[:15]:
        content = b.get("content", {})
        title = content.get("title") or content.get("url") or b.get("title", "(untitled)")
        url = content.get("url", "")
        print(f"• {title}\n  {url}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__); sys.exit(0)
    cmd = args[0]
    if cmd == "add":
        # add <url> [--tags a,b,c] [note words...]
        rest = args[2:]
        tags = None
        if "--tags" in rest:
            i = rest.index("--tags")
            tags = [t.strip() for t in rest[i + 1].split(",") if t.strip()] if i + 1 < len(rest) else None
            rest = rest[:i] + rest[i + 2:]
        cmd_add(args[1], " ".join(rest), tags)
    elif cmd == "tag":
        cmd_tag(args[1], [t.strip() for t in " ".join(args[2:]).replace(",", " ").split() if t.strip()])
    elif cmd == "note":
        cmd_note(" ".join(args[1:]))
    elif cmd == "search":
        cmd_search(" ".join(args[1:]))
    else:
        print(__doc__)
