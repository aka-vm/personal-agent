#!/usr/bin/env python3
"""
Splitwise payment reminders via WhatsApp.

Runs daily. Only active after the 5th of each month.
  --dry-run : preview mode — message Vineet instead of the debtor
  --force   : skip date check (for testing)

Rules:
  > ₹10k  → remind every 3 days
  > ₹5k   → remind every 7 days
"""

import json, os, sys, subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

THRESHOLD_LOW  = 5_000
THRESHOLD_HIGH = 10_000
INTERVAL_LOW   = 7   # days between reminders for 5k-10k
INTERVAL_HIGH  = 3   # days between reminders for >10k

MY_ID          = 64836932
RPI_BOT_GROUP  = "120363428792287616@g.us"
START_DAY      = 5   # only active from this day of month

# Splitwise user ID → (name, WhatsApp number in 91XXXXXXXXXX format)
# Add numbers here as you learn them
CONTACTS = {
    50382709: ("Nived",      "919744810125"),
    53697061: ("Ansh",       "919817449619"),
    72844773: ("Madhurima",  None),
    43590889: ("Prabhav",    None),
    74711554: ("Ayush",      None),
    46927292: ("Abinash",    None),
    49603879: ("Abhinav",    None),
    49694874: ("Shashikant", None),
    52501317: ("Manish",     None),
    37294760: ("Priyanshu",  None),
    53433845: ("Eshaan",     None),
}

STATE_FILE = Path.home() / ".config/agent/payment_reminder_state.json"
AGENT_ROOT = Path(__file__).parent.parent
SW_SCRIPT  = AGENT_ROOT / "services/splitwise/sw.py"
WA_SCRIPT  = AGENT_ROOT / "tools/wa.py"

DRY_RUN = "--dry-run" in sys.argv
FORCE   = "--force"   in sys.argv

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

def get_splitwise_balances():
    """Returns list of (user_id, first_name, amount_inr) owed TO Vineet."""
    import base64, hashlib, hmac, time, uuid, urllib.parse, requests

    creds_file = Path.home() / ".config/splitwise/creds.json"
    creds = json.loads(creds_file.read_text())

    def percent_encode(s):
        return urllib.parse.quote(str(s), safe="")

    def auth_header(method, url):
        op = {
            "oauth_consumer_key": creds["consumer_key"],
            "oauth_nonce": uuid.uuid4().hex,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": creds["access_token"],
            "oauth_version": "1.0",
        }
        ps = "&".join(
            f"{percent_encode(k)}={percent_encode(v)}"
            for k, v in sorted(op.items())
        )
        bs = f"{method.upper()}&{percent_encode(url)}&{percent_encode(ps)}"
        sk = f"{percent_encode(creds['consumer_secret'])}&{percent_encode(creds['access_token_secret'])}"
        sig = base64.b64encode(
            hmac.new(sk.encode(), bs.encode(), hashlib.sha1).digest()
        ).decode()
        op["oauth_signature"] = sig
        return "OAuth " + ", ".join(
            f'{k}="{percent_encode(v)}"' for k, v in sorted(op.items())
        )

    url = "https://secure.splitwise.com/api/v3.0/get_friends"
    r = __import__("requests").get(
        url, headers={"Authorization": auth_header("GET", url)}, timeout=15
    )
    friends = r.json().get("friends", [])

    result = []
    for f in friends:
        for b in f.get("balance", []):
            if b["currency_code"] == "INR" and float(b["amount"]) > 0:
                result.append((f["id"], f["first_name"], float(b["amount"])))
    return result

def wa_send_group(msg):
    subprocess.run(
        ["python3", str(WA_SCRIPT), "send_group", RPI_BOT_GROUP, msg],
        check=True
    )

def wa_send_person(number, msg):
    subprocess.run(
        ["python3", str(WA_SCRIPT), "send", number, msg, ""],
        check=True
    )

def reminder_message(name):
    return (
        f"Hi {name}, this is a friendly reminder that you have a pending "
        f"balance on Splitwise. No need to reply — this is an automated message."
    )

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today = date.today()

    if not FORCE and today.day < START_DAY:
        log(f"Day {today.day} < {START_DAY}, skipping until after the 5th.")
        return

    log(f"Fetching Splitwise balances (dry_run={DRY_RUN})...")
    balances = get_splitwise_balances()
    state = load_state()
    today_str = today.isoformat()

    pending   = []   # will actually send (or preview)
    skipped   = []   # not due yet / below threshold / no number

    for user_id, first_name, amount in balances:
        uid = str(user_id)

        if amount < THRESHOLD_LOW:
            skipped.append(f"{first_name}: ₹{amount:,.0f} (below ₹5k threshold)")
            continue

        interval = INTERVAL_HIGH if amount >= THRESHOLD_HIGH else INTERVAL_LOW
        last_str = state.get(uid, {}).get("last_sent")

        if last_str:
            last_date = date.fromisoformat(last_str)
            days_since = (today - last_date).days
            if days_since < interval:
                skipped.append(
                    f"{first_name}: ₹{amount:,.0f} — sent {days_since}d ago, "
                    f"next in {interval - days_since}d"
                )
                continue

        name, number = CONTACTS.get(user_id, (first_name, None))

        if number is None:
            skipped.append(f"{name}: ₹{amount:,.0f} — no WhatsApp number on file")
            continue

        interval_label = f"every {interval}d"
        pending.append({
            "user_id": uid,
            "name": name,
            "number": number,
            "amount": amount,
            "interval": interval,
            "interval_label": interval_label,
            "msg": reminder_message(name),
        })

    if not pending:
        log("Nothing to send today.")
        if skipped:
            log("Skipped:\n" + "\n".join(f"  • {s}" for s in skipped))
        return

    if DRY_RUN:
        lines = ["*[Payment Reminders — DRY RUN]*", "Would send:"]
        for p in pending:
            lines.append(
                f"• {p['name']} (₹{p['amount']:,.0f}, {p['interval_label']}): "
                f"\"{p['msg']}\""
            )
        if skipped:
            lines.append("\nSkipped:")
            for s in skipped:
                lines.append(f"• {s}")
        lines.append("\n_Testing mode — no messages sent._")
        preview = "\n".join(lines)
        log("DRY RUN — sending preview to Vineet.")
        wa_send_group(preview)
        return

    # Live mode
    for p in pending:
        log(f"Sending reminder to {p['name']} ({p['number']})...")
        wa_send_person(p["number"], p["msg"])
        state[p["user_id"]] = {"last_sent": today_str, "amount": p["amount"]}
        log(f"  ✓ sent")

    save_state(state)
    log("Done. State saved.")

    if skipped:
        log("Skipped:\n" + "\n".join(f"  • {s}" for s in skipped))


if __name__ == "__main__":
    main()
