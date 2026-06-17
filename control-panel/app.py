#!/usr/bin/env python3
"""
Control backend (host systemd service, :8090). JSON API only — the dashboard UI
is served by the hub nginx on :80, which proxies /api/ here.

- start/stop services (docker)
- global on/off (optional services; core stays up)
- single ngrok tunnel ON/OFF -> the gateway (:8081, path-routes services).
  When ON, a service is reachable at <ngrok-base>/<name>/. The dashboard (:80)
  is NEVER part of the gateway, so it's never exposed publicly.
"""
import json, subprocess, urllib.request, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GATEWAY_PORT = 8081  # nginx gateway that path-routes services; ngrok points here

SERVICES = {
    "excalidraw":   {"containers": ["excalidraw"], "core": False, "label": "Excalidraw"},
    "karakeep":     {"containers": ["karakeep-web-1", "karakeep-meilisearch-1", "karakeep-chrome-1"], "core": False, "label": "Karakeep"},
    "n8n":          {"containers": ["n8n"], "core": False, "label": "n8n"},
    "playwright":   {"containers": ["playwright-mcp-playwright-mcp-1"], "core": False, "label": "Browser (Playwright)"},
    "homeassistant":{"containers": ["homeassistant"], "core": True, "label": "Home Assistant"},
    "whatsapp":     {"containers": ["whatsapp-baileys-whatsapp-1"], "core": True, "label": "WhatsApp bridge"},
}

ngrok_proc = None


def docker_running():
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
    return set(out.split())


def ngrok_base():
    try:
        d = json.loads(urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=4).read())
        return d["tunnels"][0]["public_url"] if d.get("tunnels") else None
    except Exception:
        return None


def status():
    running = docker_running()
    base = ngrok_base()
    svc = {}
    for name, cfg in SERVICES.items():
        up = sum(1 for c in cfg["containers"] if c in running)
        svc[name] = {
            "label": cfg["label"], "core": cfg["core"],
            "state": "up" if up == len(cfg["containers"]) else ("partial" if up else "down"),
            "public": f"{base}/{name}/" if base else None,
        }
    return {"services": svc, "ngrok": base}


def set_service(name, action):
    if name in SERVICES:
        for c in SERVICES[name]["containers"]:
            subprocess.run(["docker", action, c], capture_output=True)


def ngrok_on():
    global ngrok_proc
    if ngrok_base():
        return ngrok_base()
    ngrok_proc = subprocess.Popen(
        ["/home/vineet/.local/bin/ngrok", "http", str(GATEWAY_PORT), "--log", "stdout"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(12):
        time.sleep(1)
        if ngrok_base():
            return ngrok_base()
    return None


def ngrok_off():
    global ngrok_proc
    if ngrok_proc:
        ngrok_proc.terminate()
        try: ngrok_proc.wait(5)
        except Exception: ngrok_proc.kill()
    ngrok_proc = None
    subprocess.run(["pkill", "-f", "ngrok http"], capture_output=True)


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
        if p[:2] == ["api", "ngrok"] and len(p) == 3:
            return self._j(200, {"ngrok": ngrok_on() if p[2] == "on" else (ngrok_off() or None)})
        self._j(404, {})


if __name__ == "__main__":
    print("control backend on :8090")
    ThreadingHTTPServer(("127.0.0.1", 8090), H).serve_forever()
