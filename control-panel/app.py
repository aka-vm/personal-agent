#!/usr/bin/env python3
"""
Control backend (host systemd service, :8090). JSON API only — the hub nginx (:80)
serves the dashboard and proxies /api/ here.

Just service controls: status, per-service start/stop, and global start/stop of
optional services (core stays up). No public sharing (ngrok removed).
"""
import json, subprocess, os, base64, threading, html, urllib.request, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SECRETS_PATH = os.path.expanduser("~/.config/agent/secrets.env")


def load_secrets():
    """Tiny KEY=value parser, read fresh each call so newly-added creds work
    without restarting the service."""
    s = {}
    if os.path.exists(SECRETS_PATH):
        for line in open(SECRETS_PATH):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if v[:1] in ('"', "'"):          # quoted: take content between quotes
                v = v[1:].split(v[0], 1)[0]
            else:                            # unquoted: drop any inline # comment
                v = v.split("#", 1)[0].strip()
            s[k.strip()] = v
    return s


# Escape-call scenarios: key -> what the fake caller "says" (Twilio TTS).
SCENARIOS = {
    "generic":  "Hey! Are you free right now? I really need to talk to you, it's kind of important.",
    "mom":      "Beta where are you? Everyone is waiting at home, please come quickly.",
    "boss":     "Hi, sorry to call — there's an urgent issue at work, can you join a quick call right now?",
    "reminder": "This is your reminder. You need to leave now for your next appointment.",
}


def phone_options():
    """Destination numbers from secrets -> [{id,label,number}], deduped by number."""
    s = load_secrets()
    opts, seen = [], set()
    for key in ("MY_PHONE_NUMBER", "MY_PHONE_NUMBER_2", "MY_PHONE_NUMBER_3", "TWILIO_TO_NUMBER"):
        num = s.get(key)
        if num and num not in seen:
            seen.add(num)
            opts.append({"id": key, "label": "…" + num[-4:], "number": num})
    return opts


def place_call(message, to):
    s = load_secrets()
    sid, token = s.get("TWILIO_ACCOUNT_SID"), s.get("TWILIO_AUTH_TOKEN")
    frm = s.get("TWILIO_FROM_NUMBER")
    if not all([sid, token, frm, to]):
        print("[escape] missing Twilio creds in secrets.env")
        return
    safe = html.escape(message)
    twiml = (f'<Response><Pause length="1"/><Say voice="Polly.Aditi">{safe}</Say>'
             f'<Pause length="1"/><Say voice="Polly.Aditi">{safe}</Say></Response>')
    data = urllib.parse.urlencode({"To": to, "From": frm, "Twiml": twiml}).encode()
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json",
        data=data, method="POST",
        headers={"Authorization": f"Basic {auth}",
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"[escape] call queued ({r.status})")
    except Exception as e:
        print(f"[escape] call failed: {e}")


def schedule_call(delay, scenario, phone_id=None):
    msg = SCENARIOS.get(scenario, SCENARIOS["generic"])
    opts = phone_options()
    to = next((o["number"] for o in opts if o["id"] == phone_id), None)
    if not to and opts:
        to = opts[0]["number"]
    delay = max(0, min(int(delay), 600))   # clamp 0..10 min
    if to:
        threading.Timer(delay, place_call, args=(msg, to)).start()
    return delay


# logical service -> containers, local port (web UI), core flag
SERVICES = {
    "karakeep":      {"containers": ["karakeep-web-1", "karakeep-meilisearch-1", "karakeep-chrome-1"], "core": False, "web": True,  "port": 3000, "label": "Karakeep"},
    "n8n":           {"containers": ["n8n"], "core": False, "web": True,  "port": 5678, "label": "n8n"},
    "homeassistant": {"containers": ["homeassistant"], "core": True,  "web": True,  "port": 8123, "label": "Home Assistant"},
    "whatsapp":      {"containers": ["whatsapp-baileys-whatsapp-1"], "core": True, "web": False, "port": 3001, "label": "WhatsApp bridge"},
}


def docker_running():
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
    return set(out.split())


def status():
    running = docker_running()
    svc = {}
    for name, cfg in SERVICES.items():
        up = sum(1 for c in cfg["containers"] if c in running)
        svc[name] = {
            "label": cfg["label"], "core": cfg["core"], "web": cfg["web"], "port": cfg["port"],
            "state": "up" if up == len(cfg["containers"]) else ("partial" if up else "down"),
        }
    return {"services": svc, "phones": [{"id": o["id"], "label": o["label"]} for o in phone_options()]}


def set_service(name, action):
    if name in SERVICES:
        for c in SERVICES[name]["containers"]:
            subprocess.run(["docker", action, c], capture_output=True)


class H(BaseHTTPRequestHandler):
    def _j(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path == "/api/status":
            return self._j(200, status())
        self._j(404, {})

    def do_POST(self):
        p = self.path.strip("/").split("/")
        if p[:2] == ["api", "services"] and len(p) == 4:
            set_service(p[2], "start" if p[3] == "start" else "stop"); return self._j(200, {})
        if p[:2] == ["api", "global"] and len(p) == 3:
            for name, cfg in SERVICES.items():
                if not cfg["core"]:
                    set_service(name, "start" if p[2] == "on" else "stop")
            return self._j(200, {})
        if p == ["api", "escape-call"]:
            n = int(self.headers.get("Content-Length", 0) or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            s = load_secrets()
            ok = (all(s.get(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"))
                  and phone_options())
            if not ok:
                return self._j(503, {"error": "Twilio not configured"})
            delay = schedule_call(body.get("delay", 60), body.get("scenario", "generic"), body.get("phone"))
            return self._j(200, {"ok": True, "delay": delay})
        self._j(404, {})


if __name__ == "__main__":
    print("control backend on :8090")
    ThreadingHTTPServer(("127.0.0.1", 8090), H).serve_forever()
