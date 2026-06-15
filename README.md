# Personal Agent

A self-hosted personal assistant built on **Claude Code**, reachable over
Telegram and WhatsApp. It runs on a Raspberry Pi (or any always-on Linux box)
and acts on your behalf across calendar, email, contacts, smart home, expenses,
and the web.

## Architecture

```
                  ┌─────────────────────────────┐
   Telegram ─────▶│  adapters/telegram_bot.py    │
                  │  adapters/whatsapp_bot.py    │──┐
   WhatsApp ─────▶│  (thin I/O only)             │  │
                  └─────────────────────────────┘  │
                                                    ▼
                                       ┌─────────────────────────┐
                                       │      core/agent.py       │  one brain
                                       │  commands, file markers  │
                                       └────────────┬────────────┘
                                                    ▼
                                       ┌─────────────────────────┐
                                       │   core/claude_runner.py  │
                                       │  `claude -p` + native    │
                                       │  session resume per      │
                                       │  conversation            │
                                       └────────────┬────────────┘
                                                    ▼
                                       ┌─────────────────────────┐
                                       │   claude (Claude Code)   │
                                       │  CLAUDE.md = system      │
                                       │  prompt + service catalog│
                                       │  tools/  = its hands     │
                                       │  memory/ = long-term mem │
                                       └─────────────────────────┘
```

Key design choices:
- **One core, thin adapters.** All logic lives in `core/`; Telegram/WhatsApp
  files only do channel I/O. No duplicated brains.
- **Native session resume.** Each conversation maps to a Claude Code session id
  (persisted to disk). Context — including tool calls — survives restarts. No
  hand-built history strings.
- **CLAUDE.md is the system prompt.** Auto-loaded by `claude` from the repo root.
- **Memory is a file.** `memory/MEMORY.md` is imported by CLAUDE.md every turn;
  the agent edits it to remember preferences and facts.
- **Secrets live outside the repo** in `~/.config/agent/`. Nothing personal is
  ever committed.

## Layout
```
core/        agent brain, claude runner, config loader
adapters/    telegram + whatsapp I/O (thin)
tools/       CLI scripts the agent calls (gcal, gmail, contacts, weather, …)
tasks/       scheduled jobs (alerts, briefings) run via cron
services/    per-service catalogs the agent reads for how-to + credentials
config/      *.example templates (real config lives in ~/.config/agent/)
systemd/     unit files for the adapters
memory/      long-term memory (MEMORY.md, gitignored; .example committed)
CLAUDE.md    the agent's system prompt + service catalog
```

## Setup (replicate this)
See `SETUP.md`. In short:
1. Install the `claude` CLI and log in.
2. `cp config/config.example.yaml ~/.config/agent/config.yaml` and edit.
3. `cp config/secrets.example.env ~/.config/agent/secrets.env`, add your
   Telegram bot token, `chmod 600`.
4. `cp memory/MEMORY.example.md memory/MEMORY.md`.
5. Add per-service credentials (see each `services/*/info.md`).
6. Install + start the systemd units in `systemd/`.
