#!/usr/bin/env python3
"""
Control panel — start/stop services, global on/off, and on-demand public links
(ngrok). Runs as a host systemd user service (has docker-group + ngrok access).
Serves UI + JSON API on :8090, reachable over Tailscale.
"""
import json, subprocess, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# logical service -> containers, local port, whether it's core (never auto-stopped)
SERVICES = {
    "excalidraw":   {"containers": ["excalidraw"], "port": 5001, "core": False, "label": "Excalidraw"},
    "karakeep":     {"containers": ["karakeep-web-1", "karakeep-meilisearch-1", "karakeep-chrome-1"], "port": 3000, "core": False, "label": "Karakeep"},
    "n8n":          {"containers": ["n8n"], "port": 5678, "core": False, "label": "n8n"},
    "playwright":   {"containers": ["playwright-mcp-playwright-mcp-1"], "port": 3333, "core": False, "label": "Browser (Playwright)"},
    "homeassistant":{"containers": ["homeassistant"], "port": 8123, "core": True, "label": "Home Assistant"},
    "whatsapp":     {"containers": ["whatsapp-baileys-whatsapp-1"], "port": 3001, "core": True, "label": "WhatsApp bridge"},
}

ngrok_proc = None
ngrok_service = None


def docker_running():
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
    return set(out.split())


def service_status():
    running = docker_running()
    res = {}
    for name, cfg in SERVICES.items():
        up = sum(1 for c in cfg["containers"] if c in running)
        res[name] = {
            "label": cfg["label"], "core": cfg["core"], "port": cfg["port"],
            "state": "up" if up == len(cfg["containers"]) else ("partial" if up else "down"),
            "shared": ngrok_service == name,
        }
    return res


def set_service(name, action):
    if name not in SERVICES:
        return
    for c in SERVICES[name]["containers"]:
        subprocess.run(["docker", action, c], capture_output=True)


def ngrok_url():
    try:
        d = json.loads(urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=4).read())
        return d["tunnels"][0]["public_url"] if d.get("tunnels") else None
    except Exception:
        return None


def ngrok_start(name):
    global ngrok_proc, ngrok_service
    ngrok_stop()
    if name not in SERVICES:
        return None
    port = SERVICES[name]["port"]
    ngrok_proc = subprocess.Popen(["/home/vineet/.local/bin/ngrok", "http", str(port), "--log", "stdout"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ngrok_service = name
    import time
    for _ in range(10):
        time.sleep(1)
        u = ngrok_url()
        if u:
            return u
    return None


def ngrok_stop():
    global ngrok_proc, ngrok_service
    if ngrok_proc:
        ngrok_proc.terminate()
        try: ngrok_proc.wait(5)
        except Exception: ngrok_proc.kill()
    ngrok_proc = None
    ngrok_service = None


PAGE = """<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Pi Control</title><style>
body{font-family:system-ui,sans-serif;background:#0f1115;color:#e6e6e6;margin:0;padding:18px;max-width:680px;margin:auto}
h1{font-size:20px} .bar{display:flex;gap:10px;margin:14px 0}
button{background:#2a2f3a;color:#e6e6e6;border:0;border-radius:8px;padding:9px 14px;cursor:pointer;font-size:14px}
button:hover{background:#3a4150} .on{background:#1f6f3f}.off{background:#7a2630}
.card{background:#181c24;border-radius:12px;padding:14px;margin:10px 0;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.dot{width:10px;height:10px;border-radius:50%}.up{background:#3fbf6f}.down{background:#777}.partial{background:#d9a441}
.name{flex:1;font-weight:600}.core{font-size:11px;color:#888;border:1px solid #444;border-radius:5px;padding:1px 5px}
.url{flex-basis:100%;font-size:12px;color:#6cb0ff;word-break:break-all}
small{color:#888}</style></head><body>
<h1>⚙️ Pi Control Panel</h1>
<div class=bar>
  <button class=on onclick="g('on')">▶ Global ON</button>
  <button class=off onclick="g('off')">⏹ Global OFF (optional services)</button>
</div>
<div id=services></div>
<small>Global OFF stops optional services; core (WhatsApp bridge, HA) stays up. Public links via ngrok are on-demand.</small>
<script>
async function load(){
  const s = await (await fetch('/api/services')).json();
  const box = document.getElementById('services'); box.innerHTML='';
  for(const [k,v] of Object.entries(s)){
    const up = v.state==='up';
    box.innerHTML += `<div class=card>
      <span class="dot ${v.state}"></span>
      <span class=name>${v.label} ${v.core?'<span class=core>core</span>':''}</span>
      <button onclick="svc('${k}','${up?'stop':'start'}')">${up?'Stop':'Start'}</button>
      <button onclick="share('${k}')">${v.shared?'🔗 Stop share':'🌐 Share'}</button>
      ${v.shared?`<span class=url id=u_${k}></span>`:''}
    </div>`;
  }
  const u = await (await fetch('/api/ngrok')).json();
  if(u.url && u.service){ const el=document.getElementById('u_'+u.service); if(el) el.textContent=u.url; }
}
async function svc(k,a){ await fetch('/api/services/'+k+'/'+a,{method:'POST'}); setTimeout(load,1500); }
async function g(a){ await fetch('/api/global/'+a,{method:'POST'}); setTimeout(load,2500); }
async function share(k){ const r=await (await fetch('/api/ngrok/'+k,{method:'POST'})).json(); load(); if(r.url) alert('Public link:\\n'+r.url); }
load(); setInterval(load,8000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def log_message(self, *a): pass

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            return self._send(200, PAGE, "text/html")
        if self.path == "/api/services":
            return self._send(200, json.dumps(service_status()))
        if self.path == "/api/ngrok":
            return self._send(200, json.dumps({"url": ngrok_url(), "service": ngrok_service}))
        self._send(404, "{}")

    def do_POST(self):
        p = self.path.strip("/").split("/")
        if p[:2] == ["api", "services"] and len(p) == 4:
            set_service(p[2], "start" if p[3] == "start" else "stop")
            return self._send(200, "{}")
        if p[:2] == ["api", "global"] and len(p) == 3:
            for name, cfg in SERVICES.items():
                if not cfg["core"]:
                    set_service(name, "start" if p[2] == "on" else "stop")
            return self._send(200, "{}")
        if p[:2] == ["api", "ngrok"] and len(p) == 3:
            if ngrok_service == p[2]:
                ngrok_stop(); return self._send(200, json.dumps({"url": None}))
            return self._send(200, json.dumps({"url": ngrok_start(p[2])}))
        self._send(404, "{}")


if __name__ == "__main__":
    print("control panel on :8090")
    ThreadingHTTPServer(("0.0.0.0", 8090), H).serve_forever()
