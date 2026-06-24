# Token / Bloat Reduction Audit — personal-agent

*Generated from a live scan of the agent + current web best-practices. Recommend-only.*

## How tokens are actually spent here
The agent runs `claude -p --resume <session>` per turn (model **claude-sonnet-4-6**), from `/home/vineet/agent`. **Every turn re-sends:**
- Claude Code's base system prompt (fixed)
- **CLAUDE.md** — 145 lines / ~9 KB (~2.2K tokens)
- **`@memory/MEMORY.md`** imported every turn — 102 lines / ~10 KB (~2.6K tokens)
- **Always-on MCP tool schemas** — `playwright` + `homeassistant` (from `~/.claude.json`)
- **The resumed conversation history** — and this is the catch (below)

✅ Good already: `services/*/info.md` (25 KB total) are **lazy pointers**, read on demand — not loaded every turn. `daily_briefing` already uses a **fresh session per day**. Model is **Sonnet, not Opus**.

---

## Findings (prioritized)

### 🔴 HIGH

**1. The conversational session never resets → unbounded context growth.**
`whatsapp:rpibot` resumes the **same session id forever** (`5b88fb0c…`); the session store is already **29 MB**. Every WhatsApp message re-processes the entire accumulated history, so cost climbs with every message and never comes back down. This is the dominant, ever-growing token sink.
- **Fix:** cap it — auto-`/reset` daily (mirror `daily_briefing`'s fresh-session-per-day), or after N turns, or summarize-and-restart (a cheap model writes the summary; "compaction" can cut accumulated state ~98%). Long-term facts live in `MEMORY.md`, so a reset only drops short-term chatter.
- Impact: **HIGH** · Effort: LOW–MED · Risk: LOW

**2. Playwright MCP is always-on but rarely used.**
`~/.claude.json` loads `playwright` + `homeassistant` for **every** agent turn. Playwright's browser tool-schema is large; and since the container is off by default, each run also pays a **connection timeout**. The agent almost never browses.
- **Fix:** remove `playwright` from the always-on `mcpServers`; start it on demand only for browser tasks (or use `shot.sh`, which doesn't need the MCP). Keep `homeassistant` (actually used).
- Impact: **MED–HIGH** · Effort: LOW · Risk: LOW

### 🟠 MEDIUM

**3. Always-loaded CLAUDE.md + MEMORY.md ≈ ~5K tokens every turn.**
CLAUDE.md (145 lines) is under Anthropic's ~200-line guidance, but `MEMORY.md` grows as memories accumulate. With sporadic WhatsApp gaps **> the 5-min cache TTL**, this prefix isn't cached → paid in full each message.
- **Fix:** tighten CLAUDE.md (trim Tools/Notes), periodically prune/condense `MEMORY.md` (archive stale entries), push rarely-needed detail into lazy `info.md` pointers (pattern already in use).
- Impact: **MED** · Effort: LOW · Risk: LOW

**4. Route low-energy tasks to a cheaper model.**
Already Sonnet (not Opus), so the win is **Sonnet → Haiku** (or a credit-based model) for trivial work: one-line WhatsApp acks, classification, the session-compaction summaries (#1), daily-briefing. (Voice already on Groq; Karakeep tagging already Gemini.) You're open to a credit-based LLM — best ROI is compaction-summaries + simple replies.
- Impact: **MED** · Effort: MED (per-task model selection) · Risk: LOW–MED (quality on edge cases)

**5. Make prompt caching actually hit.**
Claude Code auto-caches the stable prefix (system + CLAUDE.md + tools) at **~10% cost**, but the 5-min TTL means sporadic messages miss it. Keep the prefix **stable** — don't vary CLAUDE.md / MCP set / model between turns — so clustered messages cache. Compounds with #1 (smaller resumed history = less to cache/re-read).
- Impact: **MED** (when messages cluster) · Effort: LOW · Risk: NONE

### 🟢 LOW / cleanup
- **6.** Prune stale `state/sessions.json` entries (old `task:daily-briefing` + `telegram`). Trivial.
- **7.** Keep `info.md` files lazy — never `@import` them.

---

## Top 3 do-first
1. **Cap the conversational session** (auto-reset daily / after N turns, or summarize-restart) — biggest, ever-growing win.
2. **Drop Playwright from always-on MCPs → on-demand** — easy, immediate per-turn saving.
3. **Trim CLAUDE.md + prune MEMORY.md**, and keep the prefix stable so caching hits.

## Sources
- [Claude Code — Manage costs effectively](https://code.claude.com/docs/en/costs)
- [Claude Code context window / token optimization](https://claudefa.st/blog/guide/mechanics/context-management)
- [Prompt caching — Claude API docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Compaction vs summarization (Morph)](https://www.morphllm.com/compaction-vs-summarization)
- [Compressing context (Factory.ai)](https://factory.ai/news/compressing-context)
- [Token-saving tips for Claude Code](https://www.mindstudio.ai/blog/how-to-manage-claude-code-token-usage)
