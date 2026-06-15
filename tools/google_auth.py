#!/usr/bin/env python3
"""
Google OAuth setup — run once per account.
Usage:
  python3 google_auth.py personal
  python3 google_auth.py work
"""
import sys, os, json, urllib.parse
from google_auth_oauthlib.flow import InstalledAppFlow

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from google_scopes import SCOPES

CLIENT_SECRET = os.path.expanduser("~/.config/google/client_secret.json")
CONFIG_DIR    = os.path.expanduser("~/.config/google")

def auth(account):
    token_file = os.path.join(CONFIG_DIR, f"{account}_token.json")

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
    flow.redirect_uri = "http://localhost:8080"

    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")

    print(f"\n{'='*60}")
    print(f"Authorising: {account} account")
    print(f"{'='*60}")
    print("\n1. Open this URL on your MacBook:\n")
    print(f"   {auth_url}\n")
    print("2. Sign in with your", "PERSONAL" if account == "personal" else "WORK", "Google account")
    print("3. After approving, your browser will show")
    print("   'This site can't be reached' on localhost:8080 — that's expected.")
    print("4. Copy the FULL URL from the address bar and paste it below.\n")

    redirect_url = input("Paste the full redirect URL here: ").strip()

    parsed = urllib.parse.urlparse(redirect_url)
    params = urllib.parse.parse_qs(parsed.query)
    code = params.get("code", [None])[0]
    if not code:
        print("Error: could not find 'code' in URL. Make sure you copied the full URL.")
        sys.exit(1)

    flow.fetch_token(code=code)
    creds = flow.credentials

    with open(token_file, "w") as f:
        f.write(creds.to_json())
    print(f"\n✓ Token saved → {token_file}")

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("personal", "work"):
        print("Usage: python3 google_auth.py personal|work")
        sys.exit(1)
    auth(sys.argv[1])
