# Hub dashboard & personal apps

> Load this only when working on the hub dashboard or adding/serving a personal app.

## Layout
- **Dashboard UI:** `/home/vineet/hub/html/index.html` — DIR-mounted into the `hub` nginx
  container, so edits are **live, no restart**. Repo mirror: `agent/docker/hub/html/index.html`.
- **Backend API:** `control-panel` (systemd **user** service, `127.0.0.1:8090`), proxied by the
  hub nginx at `/api/`. File: `/home/vineet/control-panel/app.py` (mirror `agent/control-panel/app.py`).
- **Sections in the html:** Docker service cards (start/stop), the **Escape Call** card, and an
  **Apps** list driven by the `APPS` array in the script.

## The model: each app is its own repo
Apps are **separate GitHub repos** (private by default — see memory `app-repo-workflow`). The
dashboard contains **no app code** — it only links to apps, each served on its **own HTTPS port**
via Tailscale. HTTPS per app matters: mic/`getUserMedia`, clipboard, and other browser features
need a secure context; `tailscale serve` provides a real cert for the `*.ts.net` host.

Current apps / ports:
- STFU              → `https://vineet.werewolf-platy.ts.net:8443/`  (external repo)
- Encoder · Decoder → `https://vineet.werewolf-platy.ts.net:8444/`  (repo `aka-vm/encoder-decoder`)
- **Ports used: 8443, 8444 — next free: 8445.**

## Add a personal app (easy + replicable from GH)
1. App is its own GH repo (`aka-vm/<name>`), ideally self-contained static files.
2. On the Pi: `git clone git@github.com:aka-vm/<name>.git /home/vineet/<name>`
3. Serve over HTTPS on a free port (needs root — `tailscale serve` requires sudo):
   `sudo tailscale serve --bg --https=<port> /home/vineet/<name>`
4. Add to the `APPS` array in the dashboard html:
   `{label:'<Name>', url:'https://vineet.werewolf-platy.ts.net:<port>/', note:'<short>'}`
   then copy to `agent/docker/hub/html/index.html` and commit.
5. Verify: `bash /home/vineet/playwright-mcp/shot.sh <url>`.

## Dashboard-integrated single-div features (e.g. Escape Call)
Some features live as a **small card in the dashboard html + a control-panel endpoint**, while the
**full app is its own repo**. Keep the dashboard side minimal (one div + button); the full UI and
extra options belong in the app's repo.

## Replicability (rebuild from GH)
`~/serve-apps.sh` (repo mirror: `serve-apps.sh`) is the single source of truth for app → port — it runs
every app's `tailscale serve --bg --https=<port> <dir>`. To add an app, add a `serve` line there.
To rebuild a fresh Pi: restore personal-agent (hub + control-panel), clone each app repo, run `serve-apps.sh`.
(`tailscale serve --bg` config persists across reboots, so it's mainly needed once per machine.)

## Debug / screenshot
`bash /home/vineet/playwright-mcp/shot.sh <url> [out.png]` — brings the off-by-default browser up,
screenshots, prints the path; the reap cron stops it after ~15 min.
