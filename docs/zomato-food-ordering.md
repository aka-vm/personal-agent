# Spec: Automated lunch ordering (Zomato)

**Status:** Parked — waiting on Zomato MCP access approval (applied via
github.com/Zomato/mcp-server-manifest questionnaire). Nothing to build until
credentials land.

## Goal
Remove the daily effort of choosing, ordering, and logging office lunch. The
agent proposes a lunch order based on availability + history; Vineet confirms in
Telegram; the agent orders, pays, and logs what he ate.

## Flow
1. **Trigger:** on a weekday, when the calendar shows a free slot in the
   **12pm–3pm** window, the agent proposes lunch (does not order silently).
2. **Selection:** suggest items based on order **history** + preferences —
   bias toward **filling, healthy** options. Offer 1–2 choices, not a wall.
3. **Confirm:** send the proposed cart + total to **Telegram**; Vineet replies
   to approve. No charge without explicit confirmation.
4. **Order + pay:** place the confirmed order via the Zomato MCP.
5. **Log:** record item(s), restaurant, price, date to a food diary for diet
   tracking (stored locally).

## Hard guardrails (enforced in code, not just prompt)
- **Max amount per order:** configurable cap (set the ₹ value at build time).
- **1 order per day** — never place a second without explicit override.
- **Time window:** orders only between **12:00–15:00**.
- **Confirm-before-pay:** always, via Telegram. (Full hands-off "usual at 1pm"
  mode can come later, behind a restaurant/item allow-list + the caps above.)

## Open decisions (resolve at build time)
- Max order amount (₹?).
- Default cuisine/restaurant allow-list for "healthy + filling".
- Where the food diary lives (e.g. `~/.config/agent/food_log.jsonl` or a
  Karakeep/Sheet) and what fields to track.
