# Setup — replicate this agent

Stand up your own instance on a Raspberry Pi or any always-on Linux box.

## 0. Prerequisites
- **Claude Code CLI**, logged in: `claude` on PATH (this uses your Claude
  subscription, not pay-per-use API credits).
- **Python 3.11+** with these packages:
  ```bash
  pip install --user pyyaml python-dotenv requests \
    google-api-python-client google-auth google-auth-oauthlib \
    caldav vobject
  ```
- **Docker** (only if you want the WhatsApp bridge).

## 1. Clone + config
```bash
git clone <your-repo> ~/agent && cd ~/agent
mkdir -p ~/.config/agent/state
cp config/config.example.yaml ~/.config/agent/config.yaml
cp config/secrets.example.env ~/.config/agent/secrets.env
cp memory/MEMORY.example.md memory/MEMORY.md
chmod 600 ~/.config/agent/config.yaml ~/.config/agent/secrets.env
```
Edit `~/.config/agent/config.yaml` (your IDs, phone, group) and
`~/.config/agent/secrets.env` (your Telegram token).

## 2. Telegram (your inbound channel)
1. Talk to **@BotFather** → `/newbot` → copy the token into `secrets.env`
   (`TELEGRAM_BOT_TOKEN=...`).
2. Get your own user id from **@userinfobot** → put it in `config.yaml`
   (`telegram.allowed_id`). Only this id can talk to the agent.

## 3. WhatsApp bridge (optional — outbound only)
Used to text people on your behalf + log to a history group.
```bash
cd ~/whatsapp-baileys && docker compose up -d        # see that repo's README
python3 tools/wa.py qr                                # scan with WhatsApp → Linked Devices
```
Set `whatsapp.owner_phone` and `whatsapp.log_group` in `config.yaml`.

## 4. Per-service credentials
Each lives under `~/.config/`, never in the repo. See each `services/*/info.md`:
- **Google** (Calendar/Gmail/Drive/Contacts): put OAuth client at
  `~/.config/google/client_secret.json`, then
  `python3 tools/google_auth.py personal` and `... work`. One consent grants all
  scopes (see `tools/google_scopes.py`).
- **Apple** (Contacts/Reminders): app-specific password at
  `~/.config/apple/creds.json`.
- **Home Assistant** (weather/location): long-lived token at
  `~/.config/homeassistant/token`.

## 5. Run it
```bash
cp systemd/agent-telegram.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agent-telegram.service
# (agent-whatsapp.service exists but is for a future inbound feature — leave off)
```
Message your bot on Telegram. Logs: `~/agent/logs/telegram.log`.

## 6. Scheduled tasks (optional)
```bash
crontab -e
# system alerts every 15 min:
*/15 * * * * /usr/bin/python3 ~/agent/tasks/alerts.py >> ~/agent/logs/alerts.log 2>&1
# morning briefing at 8am:
0 8 * * * /usr/bin/python3 ~/agent/tasks/daily_briefing.py >> ~/agent/logs/briefing.log 2>&1
```

## Optional integrations
- **Linear / other claude.ai MCPs:** authenticate once via the Claude app or
  `claude mcp` — they then work in the headless bot too.
- **GitHub:** `sudo apt install gh` then `gh auth login` (PAT with `repo`,
  `read:org`, `workflow`). The agent uses `gh` via Bash.
- **Browser (Playwright):** run the Playwright MCP (Docker, port 3333), then
  `claude mcp add --scope user --transport http playwright http://localhost:3333/mcp`.
  Note: Chromium launch on a Pi is slow (~2-4 min/task) but within the turn limit.

## Notes
- Secrets/config/memory/personal catalogs are gitignored — the repo stays clean
  to share. `*.example.*` files show the format.
- The agent runs with `--permission-mode bypassPermissions` (it's your own
  trusted box). Guardrails live in `CLAUDE.md`, not permission prompts.
