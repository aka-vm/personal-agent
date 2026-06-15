#!/usr/bin/env python3
"""
Brave Search — fast, lightweight web search (no browser needed).
Reads BRAVE_API_KEY from ~/.config/agent/secrets.env (or the environment).

Usage:
  brave.py search "<query>" [count]    — web results (default 8)
  brave.py news   "<query>" [count]    — recent news results
"""
import sys, os, re, json, urllib.parse, urllib.request
from dotenv import dotenv_values

_TAG = re.compile(r"<[^>]+>")
def _clean(s):
    return _TAG.sub("", s or "").replace("\n", " ").strip()

SECRETS = os.path.expanduser("~/.config/agent/secrets.env")
API = "https://api.search.brave.com/res/v1"


def _key():
    k = (dotenv_values(SECRETS).get("BRAVE_API_KEY")
         if os.path.exists(SECRETS) else None) or os.environ.get("BRAVE_API_KEY")
    if not k:
        print("No BRAVE_API_KEY. Add it to ~/.config/agent/secrets.env "
              "(get a free key at api-dashboard.search.brave.com).")
        sys.exit(1)
    return k


def _get(path, params):
    url = f"{API}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "X-Subscription-Token": _key(),
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def cmd_search(query, count=8):
    data = _get("web/search", {"q": query, "count": int(count)})
    results = data.get("web", {}).get("results", [])
    print(f"\n── Web: '{query}' ({len(results)}) ──")
    if not results:
        print("  No results.")
    for r in results:
        print(f"\n• {_clean(r.get('title',''))}\n  {r.get('url','')}\n  {_clean(r.get('description',''))[:200]}")


def cmd_news(query, count=8):
    data = _get("news/search", {"q": query, "count": int(count)})
    results = data.get("results", [])
    print(f"\n── News: '{query}' ({len(results)}) ──")
    if not results:
        print("  No results.")
    for r in results:
        print(f"\n• {_clean(r.get('title',''))}  ({r.get('age','')})\n  {r.get('url','')}\n  {_clean(r.get('description',''))[:200]}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in ("search", "news"):
        print(__doc__); sys.exit(0)
    cmd = args[0]
    query = args[1] if len(args) > 1 else ""
    count = args[2] if len(args) > 2 else 8
    if not query:
        print("Provide a query."); sys.exit(1)
    (cmd_search if cmd == "search" else cmd_news)(query, count)
