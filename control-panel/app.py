#!/usr/bin/env python3
"""
Control backend (host systemd service, :8090). JSON API only — the hub nginx (:80)
serves the dashboard and proxies /api/ here.

Public sharing model (free ngrok): ONE service at a time, exposed at the tunnel
ROOT (so it actually works — no sub-path breakage). Each shareable service has a
Share toggle; sharing one stops any other. The dashboard itself is never tunneled.
(Clean multi-service URLs would need paid ngrok / an own domain — planned.)
"""
import json, subprocess, urllib.request, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SERVICES = {
    "karakeep":     {"containers": ["karakeep-web-1", "karakeep-meilisearch-1", "karakeep-chrome-1"], "core": False, "shareable": True, "port": 3000, "label": "Karakeep"},
    "n8n":          {"containers": ["n8n"], "core": False, "shareable": True,  "port": 5678, "label": "n8n"},
    "playwright":   {"containers": ["playwright-mcp-playwright-mcp-1"], "core": False, "shareable": False, "port": 3333, "label": "Browser (Playwright)"},
    "homeassistant":{"containers": ["homeassistant"], "core": True, "shareable": True, "port": 8123, "label": "Home Assistant"},
    "whatsapp":     {"containers": ["whatsapp-baileys-whatsapp-1"], "core": True, "shareable": False, "port": 3001, "label": "WhatsApp bridge"},
}

ngrok_proc = None
shared = None  # name of the currently shared service


def docker_running():
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
    return set(out.split())


def ngrok_url():
    try:
        d = json.loads(urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=4).read())
        return d["tunnels"][0]["public_url"] if d.get("tunnels") else None
    except Exception:
        return None


def status():
    running = docker_running()
    base = ngrok_url()
    svc = {}
    for name, cfg in SERVICES.items():
        up = sum(1 for c in cfg["containers"] if c in running)
        svc[name] = {
            "label": cfg["label"], "core": cfg["core"], "shareable": cfg["shareable"],
            "port": cfg["port"], "web": cfg["shareable"],
            "state": "up" if up == len(cfg["containers"]) else ("partial" if up else "down"),
            "shared": shared == name,
            "url": base if shared == name else None,
        }
    return {"services": svc, "shared": shared, "url": base}


def set_service(name, action):
    if name in SERVICES:
        for c in SERVICES[name]["containers"]:
            subprocess.run(["docker", action, c], capture_output=True)


def share_stop():
    global ngrok_proc, shared
    if ngrok_proc:
        ngrok_proc.terminate()
        try: ngrok_proc.wait(5)
        except Exception: ngrok_proc.kill()
    ngrok_proc = None
    subprocess.run(["pkill", "-f", "ngrok http"], capture_output=True)
    shared = None


def share_start(name):
    """Tunnel one service at the ngrok root."""
    global ngrok_proc, shared
    if name not in SERVICES or not SERVICES[name]["shareable"]:
        return None
    share_stop()
    time.sleep(1)
    port = SERVICES[name]["port"]
    ngrok_proc = subprocess.Popen(
        ["/home/vineet/.local/bin/ngrok", "http", str(port), "--log", "stdout"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shared = name
    for _ in range(12):
        time.sleep(1)
        u = ngrok_url()
        if u:
            return u
    return None


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
        if p[:2] == ["api", "share"] and len(p) == 3:
            if shared == p[2]:
                share_stop(); return self._j(200, {"url": None})
            return self._j(200, {"url": share_start(p[2])})
        self._j(404, {})


if __name__ == "__main__":
    print("control backend on :8090")
    ThreadingHTTPServer(("127.0.0.1", 8090), H).serve_forever()
