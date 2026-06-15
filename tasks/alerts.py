#!/usr/bin/env python3
"""
System alerts — checks disk, RAM, CPU and sends Telegram if thresholds exceeded.
Tracks last alert time per issue to avoid spam (max once per 2 hours per issue).
Usage: python3 alerts.py [--force]   # --force sends even if recently alerted
"""
import sys, os, json, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.config import config
from notify import send_telegram

STATE_FILE = os.path.join(config.state_dir, "alert_state.json")
COOLDOWN   = 2 * 60 * 60  # 2 hours between same alert

THRESHOLDS = {
    "disk_root":  80,   # % used on /
    "disk_ssd":   85,   # % used on /mnt/ssd
    "ram":        85,   # % used (excluding cache)
    "swap":       70,   # % used
    "cpu_load":   2.0,  # 5-min load average (for 4-core Pi)
}

def tg_send(msg):
    return send_telegram(msg)

def load_state():
    if os.path.exists(STATE_FILE):
        try: return json.load(open(STATE_FILE))
        except: pass
    return {}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    json.dump(state, open(STATE_FILE, "w"))

def disk_usage(path):
    st = os.statvfs(path)
    total = st.f_blocks * st.f_frsize
    used  = (st.f_blocks - st.f_bfree) * st.f_frsize
    pct   = used / total * 100 if total else 0
    return used, total, pct

def ram_usage():
    lines = open("/proc/meminfo").read().splitlines()
    info = {}
    for line in lines:
        parts = line.split()
        if len(parts) >= 2:
            info[parts[0].rstrip(":")] = int(parts[1])
    total     = info.get("MemTotal", 1)
    available = info.get("MemAvailable", total)
    used_pct  = (total - available) / total * 100
    swap_total = info.get("SwapTotal", 0)
    swap_free  = info.get("SwapFree", swap_total)
    swap_pct   = (swap_total - swap_free) / swap_total * 100 if swap_total else 0
    return used_pct, swap_pct, total // 1024, (total - available) // 1024

def cpu_load():
    return float(open("/proc/loadavg").read().split()[1])  # 5-min average

def fmt_size(kb):
    if kb > 1024 * 1024: return f"{kb/1024/1024:.1f} GB"
    if kb > 1024: return f"{kb/1024:.0f} MB"
    return f"{kb} KB"

def check(force=False):
    state = load_state()
    now   = time.time()
    alerts = []

    # Disk /
    _, total_root, pct_root = disk_usage("/")
    if pct_root >= THRESHOLDS["disk_root"]:
        key = "disk_root"
        if force or now - state.get(key, 0) > COOLDOWN:
            alerts.append(f"💾 *Root disk* {pct_root:.0f}% full ({fmt_size(int(total_root/1024)*(100-pct_root)/100)} free)")
            state[key] = now

    # Disk SSD
    try:
        _, total_ssd, pct_ssd = disk_usage("/mnt/ssd")
        if pct_ssd >= THRESHOLDS["disk_ssd"]:
            key = "disk_ssd"
            if force or now - state.get(key, 0) > COOLDOWN:
                alerts.append(f"💾 *SSD* {pct_ssd:.0f}% full ({fmt_size(int(total_ssd/1024*(100-pct_ssd)/100))} free)")
                state[key] = now
    except: pass

    # RAM
    ram_pct, swap_pct, ram_total_mb, ram_used_mb = ram_usage()
    if ram_pct >= THRESHOLDS["ram"]:
        key = "ram"
        if force or now - state.get(key, 0) > COOLDOWN:
            alerts.append(f"🧠 *RAM* {ram_pct:.0f}% used ({ram_used_mb} MB / {ram_total_mb} MB)")
            state[key] = now

    if swap_pct >= THRESHOLDS["swap"]:
        key = "swap"
        if force or now - state.get(key, 0) > COOLDOWN:
            alerts.append(f"💿 *Swap* {swap_pct:.0f}% used")
            state[key] = now

    # CPU
    load = cpu_load()
    if load >= THRESHOLDS["cpu_load"]:
        key = "cpu_load"
        if force or now - state.get(key, 0) > COOLDOWN:
            alerts.append(f"⚡ *CPU load* {load:.2f} (5-min avg)")
            state[key] = now

    if alerts:
        msg = "⚠️ *Pi System Alert*\n\n" + "\n".join(alerts)
        tg_send(msg)
        print(f"Sent {len(alerts)} alert(s)")
    else:
        print(f"All OK — disk root={pct_root:.0f}% ssd={pct_ssd:.0f}% ram={ram_pct:.0f}% load={load:.2f}")

    save_state(state)

if __name__ == "__main__":
    force = "--force" in sys.argv
    check(force)
