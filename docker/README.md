# Docker sidecar services

Source for the containerized helpers the agent depends on. These run as separate
Docker Compose projects; this folder is the version-controlled source of truth.

- **whatsapp-bridge/** — Baileys-based WhatsApp gateway (HTTP API on :3001). The
  agent's WhatsApp adapter talks to it. Endpoints: /status, /qr, /send, /send-group,
  /send-file, /messages, /groups, /contacts*. Session/auth lives on disk outside
  the repo (re-pair via /qr if lost).
- **playwright-mcp/** — Playwright MCP server (:3333) for browser automation.

Deploy: copy a project to its run location and `docker compose up -d --build`.
On this Pi they currently run from `~/whatsapp-baileys` and `~/playwright-mcp`;
keep those in sync with this folder (edit here, redeploy).
