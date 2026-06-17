#!/usr/bin/env python3
"""
Shorten URL(s) for chat messages (so long links like calendar URLs don't clutter).

Uses TinyURL (public, free, no key) — fine for NON-secret links (a calendar event
URL still needs Google login to view). For genuinely sensitive URLs, do NOT use
this; a self-hosted shortener is the plan for those (not built yet — ask).

(is.gd/v.gd are unreachable from this Pi's ISP, so TinyURL is the provider.)

Usage:
  shorten.py <url> [url2 ...]      # prints one short URL per input line
"""
import sys, urllib.parse, urllib.request


def shorten(url):
    api = "https://tinyurl.com/api-create.php?url=" + urllib.parse.quote(url, safe="")
    try:
        with urllib.request.urlopen(api, timeout=10) as r:
            out = r.read().decode().strip()
        return out if out.startswith("http") else url   # on error, fall back to original
    except Exception:
        return url


if __name__ == "__main__":
    urls = sys.argv[1:]
    if not urls:
        print(__doc__); sys.exit(0)
    for u in urls:
        print(shorten(u))
