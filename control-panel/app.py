#!/usr/bin/env python3
"""
Control backend (host systemd service, :8090). JSON API only — the hub nginx (:80)
serves the dashboard and proxies /api/ here.

Just service controls: status, per-service start/stop, and global start/stop of
optional services (core stays up). No public sharing (ngrok removed).
"""
import json, subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
    return {"services": svc}


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
        self._j(404, {})


if __name__ == "__main__":
    print("control backend on :8090")
    ThreadingHTTPServer(("127.0.0.1", 8090), H).serve_forever()
