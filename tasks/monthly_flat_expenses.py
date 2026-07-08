#!/usr/bin/env python3
"""Monthly flat expenses for Flat 112c.

Recurring items are configured in config/flat_expenses.json.
Add/remove items there — script auto-calculates splits and comment.

Commands:
  run         — add all recurring items as one Splitwise entry, notify WA
  elec-check  — send electricity reminder if 2+ days since last one (daily cron)
  elec-done   — stop electricity reminders this month
"""

import base64, datetime, hashlib, hmac, json, os, subprocess, sys, time
import urllib.parse, uuid
from pathlib import Path
import requests

CONFIG_FILE = Path(__file__).parent.parent / "config" / "flat_expenses.json"
ELEC_STATE  = Path(os.path.expanduser("~/.config/agent/elec_reminder_state.json"))
LOG_FILE    = Path("/home/vineet/agent/logs/monthly_expenses.log")

FLAT_WA_GROUP = "120363422593561771@g.us"  # Flat c112 unofficial
RPI_WA_GROUP  = "120363428792287616@g.us"  # Vineet's private RPI bot group

CREDS_FILE = os.path.expanduser("~/.config/splitwise/creds.json")
BASE_URL   = "https://secure.splitwise.com/api/v3.0"

# ── Config ────────────────────────────────────────────────────────────────────
def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

def compute_owed(cfg):
    """Return {member: amount_owed} from config items."""
    members = list(cfg["members"].keys())
    n = len(members)
    owed = {m: 0.0 for m in members}
    for item in cfg["items"]:
        if item["split"] == "equal":
            share = item["amount"] / n
            for m in members:
                owed[m] += share
        elif item["split"] == "custom":
            for m, amt in item["shares"].items():
                owed[m] += amt
    return {m: round(v, 2) for m, v in owed.items()}

# ── Splitwise (OAuth 1.0) ─────────────────────────────────────────────────────
def _creds():
    with open(CREDS_FILE) as f:
        return json.load(f)

def _pct(s): return urllib.parse.quote(str(s), safe="")

def _auth(method, url, body=None):
    body = body or {}
    c = _creds()
    op = {
        "oauth_consumer_key":     c["consumer_key"],
        "oauth_nonce":            uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp":        str(int(time.time())),
        "oauth_token":            c["access_token"],
        "oauth_version":          "1.0",
    }
    ap = {**op, **{k: str(v) for k, v in body.items()}}
    ps = "&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(ap.items()))
    bs = f"{method.upper()}&{_pct(url)}&{_pct(ps)}"
    sk = f"{_pct(c['consumer_secret'])}&{_pct(c['access_token_secret'])}"
    sig = base64.b64encode(
        hmac.new(sk.encode(), bs.encode(), hashlib.sha1).digest()
    ).decode()
    op["oauth_signature"] = sig
    return "OAuth " + ", ".join(f'{k}="{_pct(v)}"' for k, v in sorted(op.items()))

def sw_post(path, payload):
    url = f"{BASE_URL}/{path}"
    sp = {k: str(v) for k, v in payload.items()}
    r = requests.post(url, headers={"Authorization": _auth("POST", url, sp)},
                      data=sp, timeout=20)
    return r.json()

# ── WA helper ─────────────────────────────────────────────────────────────────
def wa_group(jid, msg):
    subprocess.run(
        ["python3", "/home/vineet/agent/tools/wa.py", "send_group", jid, msg],
        check=True
    )

# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {msg}"
    with open(LOG_FILE, "a") as f:
        f.write(entry + "\n")

# ── State ─────────────────────────────────────────────────────────────────────
def _save_state(state):
    ELEC_STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(ELEC_STATE, "w") as f:
        json.dump(state, f)

def _load_state():
    if not ELEC_STATE.exists():
        return None
    with open(ELEC_STATE) as f:
        return json.load(f)

# ── Comment builder ───────────────────────────────────────────────────────────
def build_comment(cfg, owed):
    members = list(cfg["members"].keys())
    n = len(members)
    lines = ["Breakdown:"]
    total = 0.0
    for item in cfg["items"]:
        amt = item["amount"]
        total += amt
        if item["split"] == "equal":
            lines.append(f"• {item['name']} ₹{amt:.0f} ÷ {n} = ₹{amt/n:.2f} each")
        else:
            parts = ", ".join(f"{m.capitalize()} ₹{s:.0f}" for m, s in item["shares"].items())
            lines.append(f"• {item['name']} ₹{amt:.0f} — {parts}")
    lines.append("")
    lines.append("Total owed:")
    payer = cfg["payer"]
    for m, v in owed.items():
        suffix = " (paid for all)" if m == payer else ""
        lines.append(f"• {m.capitalize()}: ₹{v:.2f}{suffix}")
    return "\n".join(lines)

# ── Commands ──────────────────────────────────────────────────────────────────
def cmd_run():
    cfg   = load_config()
    owed  = compute_owed(cfg)
    total = sum(owed.values())
    payer = cfg["payer"]
    now   = datetime.datetime.now()
    month = now.strftime("%B %Y")

    payload = {
        "description":   f"Monthly Recurring Expenses - {month}",
        "cost":          f"{total:.2f}",
        "currency_code": "INR",
        "group_id":      str(cfg["group_id"]),
        "split_equally": "false",
    }
    for i, (name, uid) in enumerate(cfg["members"].items()):
        payload[f"users__{i}__user_id"]    = str(uid)
        payload[f"users__{i}__paid_share"] = f"{total:.2f}" if name == payer else "0.00"
        payload[f"users__{i}__owed_share"] = f"{owed[name]:.2f}"

    log(f"Creating '{payload['description']}' — total ₹{total:.2f}")
    result = sw_post("create_expense", payload)

    if result.get("errors"):
        log(f"ERROR: {result['errors']}")
        sys.exit(1)

    expense = (result.get("expenses") or [{}])[0]
    eid = expense.get("id")
    log(f"Expense created: ID {eid}")

    comment = build_comment(cfg, owed)
    if eid:
        sw_post("create_comment", {"expense_id": str(eid), "content": comment})
        log("Breakdown comment added")

    # Notify flat WA group
    item_names = " + ".join(f"{it['name']} ₹{it['amount']:.0f}" for it in cfg["items"])
    wa_msg = (
        f"Monthly Recurring Expenses added to Splitwise ({month})\n\n"
        f"{item_names}\nTotal: ₹{total:.0f}"
    )
    wa_group(FLAT_WA_GROUP, wa_msg)
    log("Flat WA group notified")

    # Start electricity reminder cycle
    _save_state({"status": "pending", "last_reminded": now.isoformat()})
    wa_group(RPI_WA_GROUP,
             f"Electricity for {month}: share the amount when you have it — I'll remind every 2 days.")
    log("Electricity reminder started")


def cmd_elec_check():
    state = _load_state()
    if not state or state.get("status") != "pending":
        return
    last = datetime.datetime.fromisoformat(state["last_reminded"])
    now  = datetime.datetime.now()
    if (now - last).days >= 2:
        wa_group(RPI_WA_GROUP, "Electricity reminder: still waiting for this month's bill amount.")
        state["last_reminded"] = now.isoformat()
        _save_state(state)
        log("Electricity follow-up sent")


def cmd_elec_done():
    _save_state({"status": "done"})
    log("Electricity reminders stopped")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        cmd_run()
    elif cmd == "elec-check":
        cmd_elec_check()
    elif cmd == "elec-done":
        cmd_elec_done()
    else:
        print(__doc__)
        sys.exit(1)
