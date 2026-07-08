# Agent backlog & project notes

> Lazy reference — read when doing a review or working on the agent itself. NOT loaded every turn.

## Projects & ongoing work

### P0 — Broken, fix first
- (none — all clear)

### Fixed in 2026-07-08 review
- ✅ Double-logging in monthly_flat_expenses.py: log() wrote to file AND printed to stdout; cron redirect caused every entry to appear twice. Fixed by removing print().
- ✅ Stale annual cron `0 9 2 7 *` sending "Fix Google OAuth" every July 2. Removed.
- ✅ Committed 4 untracked task files (monthly_flat_expenses, payment_reminders, flat_expenses.json, expense_tracker_plan.md) + group_access/gcal improvements.

### P1 — High value
- ✅ DONE: Share a link in chat → save to Karakeep — handled per CLAUDE.md (URL
  with no other instruction → `karakeep.py add` with tags). Behaviour is live.
- ✅ DONE: WhatsApp voice input (STT) — bridge downloads voice messages, adapter
  transcribes via Groq Whisper (whisper-large-v3). Groq key saved in secrets.env.
- **TODO: WhatsApp image input (vision)** — photos sent in the group are ignored.
  Bridge downloads the media, adapter passes it to Claude vision (screenshots,
  receipts, etc.). [Vineet asked for this; deferred to "later".]
- **TODO: WhatsApp document input** — same as images but for PDFs/docs. [deferred]
- **TODO: Scheduling helper / reminders delivery** — a `remind_me`-style helper so
  the agent never hand-writes cron times (IST) and reminders log + retry (fixes the
  silent-failure + UTC class). Doubles as proper reminders.
- ✅ DONE: reply/quote context — implemented for WhatsApp (bridge captures quoted
  message, adapter passes it as context).
- NOTE: Telegram unblocked in India as of June 2026. Bot @siglord2_bot re-enabled (agent-telegram.service running). Both WhatsApp and Telegram are active channels.

### P2 — Nice to have
- **TODO: WhatsApp call via bot** — Baileys has `sock.call([jid], 'audio')`. Add `/call` endpoint to `docker/whatsapp-bridge/server.js` + `wa.py call <name>` command.
- ✅ DONE: WhatsApp message chunking now splits at paragraph/line boundaries (`_split_message`).
- **TODO: Daily briefing session** — reuses persistent session key `task:daily-briefing` each day → context grows, LLM cost creeps up. Use a fresh session per run. (`tasks/daily_briefing.py`)
- **TODO: Log rotation** — `alerts.py` logs "All OK" every 15 min forever. Add logrotate or only log on state change.
- **TODO (from 2026-06-29 review): Telegram parity** — Telegram adapter lacks the WhatsApp niceties: smart chunking via `_split_message` (still hard-cuts at 4000), ⏳ placeholder + edit, 👀/✅ reactions, edited-message handling. Consider extracting a shared adapter base since the two have diverged. (model routing now shared via `core.agent.pick_model`.)
- **TODO (from 2026-06-29 review): marker-based weather capability** — the old `weather` group cap was removed (it used a `Bash(...)` allowedTool that's hard-denied in sandboxed sessions, so it silently did nothing). To re-add, build it marker-style like jio-email (adapter runs `weather.py`).

- **TODO: More reliable weather** — Open-Meteo (the API) is fine; the flaky parts are
  the dependency chain: GPS comes from Home Assistant (`person.vineet`) which can be
  stale/unavailable, and place-name reverse-geocoding uses Nominatim (rate-limited,
  fails). Fix: graceful fallback when HA location is missing (last-known / home /
  configured default), cache/replace Nominatim, and clearer "as of" + location in
  output. Consider a keyed API (OpenWeatherMap/WeatherAPI) only if Open-Meteo proves
  inaccurate — but the reliability issue is the location/geocode chain, not the API.
- **TODO: Telegram /commands shortcuts** — add `/summary`, `/weather`, `/cal` etc. as quick shortcuts.
- **TODO: Telegram smart message chunking** — currently splits at exactly 4000 chars, can cut mid-word. Fix: split at paragraph/sentence boundaries (same logic as WhatsApp `_split_message`).
- **TODO: Telegram message queue** — if agent is processing and a new message arrives, it waits silently. Add queue with "still working..." feedback.
- **TODO: Telegram edited message support** — edited messages are currently ignored entirely.
- **TODO: Telegram ⏳ placeholder edit** — send a `⏳ ...` placeholder on receipt, then edit it in-place with the final reply via `editMessageText`. Same pattern as WhatsApp adapter. Cleaner than a blank gap.
- **TODO: Telegram 👀/✅ reactions** — use `setMessageReaction` (Bot API v7.0+) to react 👀 on receipt and ✅ when done. Same acknowledgement flow as WhatsApp.

### P3 — Future / complex
- **TODO (low priority): own domain / public hosting** — get a real domain via a
  paid service so the agent can make GLOBALLY accessible links (not Tailscale-only):
  a public URL shortener for sensitive links, public-facing pages, webhooks, etc.
  Replaces the "self-hosted shortener" limitation (Tailscale links only work on the
  tailnet). Low priority.
- **TODO: Vector search for email** — index emails with embeddings (OpenAI or DeepSeek key available) for semantic search and proactive alerts. ChromaDB on Pi. Park until P0/P1 done.
- **TODO: Gmail mark as read + reply** — can summarize but can't act on inbox.
- **TODO: Robust outbound email** — currently sends via Proton through Hydroxide (free, but unofficial bridge — can break on Proton API changes, small ToS risk). When reliability matters, move to an SMTP-native provider: Posteo/Mailbox.org (~€1/mo, real inbox) or Brevo (free tier, 300/day, API-style). See secrets `PROTONMAIL_ANON_*` + hydroxide service.
- **TODO: AI answering machine** — when busy, forward calls to an AI that answers + texts/emails me a summary (caller + reason). Research done (revisit later):
    - *Cloud path (clean but $/KYC):* Bolna (pay-as-you-go voice AI, India-native, Hindi/Hinglish) + a +91 number via Plivo SIP trunk. Needs business KYC (GST/incorporation, DoT mandate) + ~few hundred ₹/mo number rental — Vineet felt the number too pricey. Twilio +1 works but forwarding from India = ISD charges per call.
    - *Old Android (free) reality:* stock Android **blocks 3rd-party access to live cellular call audio** (since Android 10) → no on-phone voice AI. Free fallback = SMS "text receptionist" (auto-reject + auto-SMS, optionally loop incoming SMS → Pi/Claude → SMS reply).
    - *If rooting:* unlocks call **recording/capture** → good for a record-a-message machine + AI summary; but injecting AI speech back into the call is device-specific/unreliable.
    - *If Linux-on-phone (postmarketOS):* full ALSA call-audio control (capture+inject) → true 2-way AI calls, BUT only on devices with mature voice-call support (e.g. PinePhone), not random Androids.
    - *Cleanest DIY hardware:* a voice-capable GSM/4G modem (e.g. SIM7600) on the Pi → Pi answers + controls audio directly, no phone-OS fight.
    - *Cheap-hardware dead ends (checked):* 2G modules (SIM800L/900A/800A) are voice-capable but **2G is sunset in India / Jio is VoLTE-only** → won't get service. Data dongles (Jio/Amazon Basics/USB 4G) are **data-only, no telephony** → can't answer calls.
    - *BEST affordable hardware (checked):* **SIMCom A7670C** (4G Cat-1, **VoLTE → works with Jio**, voice+SMS, Pi via UART/USB + AT commands) — cheaper than SIM7600 and viable in India. Caveats: (1) buy the **voice variant** (A7670C-LASS/LASE, "Data+Call+SMS"), not data-only; (2) **audio path to Pi** is the real work — route the module's analog mic/spk lines into the Pi via a codec/USB sound card (or get a HAT "with audio"); (3) needs a stout power supply (~2A spikes). SMS receptionist + auto-answer (ATA) = easy; live 2-way AI voice = the audio routing is the effort. Validated board: the common Indian **ADIY/red-PCB A7670C V1.1 breakout** (Quartz Components / Robu / Robocraze) — exposes UART+USB+audio pins, RING pin, supports audio recording → suitable. Confirm MIC/SPK pins on the exact unit; needs ~4V/2-3A supply.
    - Either way, build a Pi webhook → WhatsApp/email notification with the caller + summary.
- **Escape Call standalone repo — DONE (extracted):** `aka-vm/escape-call` (private) — stdlib `server.py` (Twilio REST, no SDK) serving a **full UI** (scenarios, multiple numbers, delay presets/custom/schedule-at-time) + a **one-div embeddable widget** (`embed.js`). Creds via gitignored `.env` (reuse his with `ESCAPE_CALL_ENV=~/.config/agent/secrets.env`). Tested: config/UI/embed serve OK; call path = same verified Twilio logic.
  - **TODO (next, after Vineet tests):** run `server.py` on the Pi (systemd + `tailscale serve` port → add to `serve-apps.sh`), **swap the dashboard escape-call card for the one-div embed**, then **remove the in-agent integration** (`/api/escape-call` in control-panel + the card) so it's no longer baked into personal-agent.
