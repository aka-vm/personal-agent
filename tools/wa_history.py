#!/usr/bin/env python3
"""WhatsApp message history logger and query tool.

All incoming WhatsApp messages (private chat + every group) are stored here
so they can be retrieved and summarised later.

Usage:
  python3 tools/wa_history.py groups                       # list all groups/chats seen
  python3 tools/wa_history.py tail   <jid|name> [N=50]    # last N messages
  python3 tools/wa_history.py since  <jid|name> <hours>   # messages from last N hours
  python3 tools/wa_history.py search <query> [jid|name]   # keyword search
  python3 tools/wa_history.py dump   <jid|name> [hours]   # plain text for LLM summary
"""
import os
import sys
import sqlite3
import time

DB_PATH = os.environ.get("WA_HISTORY_DB", "/mnt/ssd/rpi_storage/wa_history.db")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS groups (
                jid  TEXT PRIMARY KEY,
                name TEXT,
                updated_ts INTEGER
            );
            CREATE TABLE IF NOT EXISTS messages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           INTEGER NOT NULL,
                group_jid    TEXT NOT NULL,
                sender_jid   TEXT,
                sender_phone TEXT,
                text         TEXT,
                is_voice     INTEGER DEFAULT 0,
                voice_path   TEXT,
                mentions_bot INTEGER DEFAULT 0,
                quoted       TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_msg_group_ts ON messages(group_jid, ts);
            CREATE INDEX IF NOT EXISTS idx_msg_ts        ON messages(ts);
        """)


def update_group_name(jid: str, name: str):
    with _conn() as c:
        c.execute(
            "INSERT INTO groups(jid, name, updated_ts) VALUES(?,?,?) "
            "ON CONFLICT(jid) DO UPDATE SET name=excluded.name, updated_ts=excluded.updated_ts",
            (jid, name, int(time.time()))
        )


def log(m: dict, group_name: str | None = None):
    """Log a raw bridge message dict. Safe to call in a try/except — never raises."""
    try:
        init_db()
        group_jid    = m.get("from") or ""
        sender_jid   = m.get("participant") or ""
        sender_phone = m.get("senderPn") or sender_jid
        text         = (m.get("text") or "").strip()
        ts           = int(m.get("timestamp") or time.time())
        is_voice     = 1 if m.get("voicePath") else 0
        voice_path   = m.get("voicePath") or ""
        mentions_bot = 1 if m.get("mentionsMe") else 0
        quoted       = (m.get("quoted") or "").strip()[:500]

        if is_voice and not text:
            text = "[voice message]"

        if group_name:
            update_group_name(group_jid, group_name)

        with _conn() as c:
            c.execute(
                "INSERT INTO messages(ts, group_jid, sender_jid, sender_phone, "
                "text, is_voice, voice_path, mentions_bot, quoted) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (ts, group_jid, sender_jid, sender_phone,
                 text, is_voice, voice_path, mentions_bot, quoted)
            )
    except Exception as e:
        print(f"[wa_history] log error: {e}", file=sys.stderr)


# ── helpers ────────────────────────────────────────────────────────────────────

def _resolve_jid(query: str) -> str | None:
    """Match by exact JID or case-insensitive group name substring."""
    with _conn() as c:
        if query.endswith("@g.us") or query.endswith("@s.whatsapp.net"):
            return query
        rows = c.execute(
            "SELECT jid FROM groups WHERE lower(name) LIKE lower(?)",
            (f"%{query}%",)
        ).fetchall()
        if rows:
            return rows[0]["jid"]
    return None


def _fmt(row) -> str:
    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["ts"]))
    phone = (row["sender_phone"] or row["sender_jid"] or "?").split("@")[0]
    text = row["text"] or ""
    if row["quoted"]:
        text = f'(re: "{row["quoted"][:60]}...") {text}' if len(row["quoted"]) > 60 else f'(re: "{row["quoted"]}") {text}'
    return f"[{ts}] {phone}: {text}"


# ── CLI ────────────────────────────────────────────────────────────────────────

def cmd_groups():
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT g.jid, g.name, COUNT(m.id) AS cnt, MAX(m.ts) AS last "
            "FROM groups g LEFT JOIN messages m ON m.group_jid=g.jid "
            "GROUP BY g.jid ORDER BY last DESC NULLS LAST"
        ).fetchall()
    if not rows:
        print("No groups logged yet.")
        return
    for r in rows:
        name = r["name"] or r["jid"]
        last = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["last"])) if r["last"] else "never"
        print(f"{name}")
        print(f"  JID  : {r['jid']}")
        print(f"  Msgs : {r['cnt']}  (last: {last})")
        print()


def cmd_tail(jid_or_name: str, n: int = 50):
    init_db()
    jid = _resolve_jid(jid_or_name) or jid_or_name
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM messages WHERE group_jid=? ORDER BY ts DESC LIMIT ?",
            (jid, n)
        ).fetchall()
    for r in reversed(rows):
        print(_fmt(r))


def cmd_since(jid_or_name: str, hours: float):
    init_db()
    jid = _resolve_jid(jid_or_name) or jid_or_name
    since = int(time.time()) - int(hours * 3600)
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM messages WHERE group_jid=? AND ts>=? ORDER BY ts",
            (jid, since)
        ).fetchall()
    for r in rows:
        print(_fmt(r))


def cmd_search(query: str, jid_or_name: str | None = None):
    init_db()
    jid = _resolve_jid(jid_or_name) if jid_or_name else None
    with _conn() as c:
        if jid:
            rows = c.execute(
                "SELECT * FROM messages WHERE group_jid=? AND lower(text) LIKE lower(?) ORDER BY ts",
                (jid, f"%{query}%")
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM messages WHERE lower(text) LIKE lower(?) ORDER BY ts",
                (f"%{query}%",)
            ).fetchall()
    for r in rows:
        grp = r["group_jid"]
        with _conn() as c2:
            gn = c2.execute("SELECT name FROM groups WHERE jid=?", (grp,)).fetchone()
        grp_name = gn["name"] if gn else grp[:20]
        print(f"[{grp_name}] {_fmt(r)}")


def cmd_dump(jid_or_name: str, hours: float = 24):
    """Dump plain-text history suitable for passing to an LLM for summarisation."""
    init_db()
    jid = _resolve_jid(jid_or_name) or jid_or_name
    since = int(time.time()) - int(hours * 3600)
    with _conn() as c:
        gn = c.execute("SELECT name FROM groups WHERE jid=?", (jid,)).fetchone()
        rows = c.execute(
            "SELECT * FROM messages WHERE group_jid=? AND ts>=? ORDER BY ts",
            (jid, since)
        ).fetchall()
    group_name = gn["name"] if gn else jid
    print(f"=== {group_name} — last {int(hours)}h ===")
    print(f"({len(rows)} messages)\n")
    for r in rows:
        print(_fmt(r))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "groups":
        cmd_groups()
    elif cmd == "tail" and len(sys.argv) >= 3:
        cmd_tail(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 50)
    elif cmd == "since" and len(sys.argv) >= 4:
        cmd_since(sys.argv[2], float(sys.argv[3]))
    elif cmd == "search" and len(sys.argv) >= 3:
        cmd_search(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif cmd == "dump" and len(sys.argv) >= 3:
        cmd_dump(sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 24)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
