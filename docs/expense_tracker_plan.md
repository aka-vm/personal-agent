# Expense Tracker — Plan

Goal: Automatically track Vineet's personal expenses, net of shared splits,
with weekly + monthly analytical summaries. Keep it simple.

---

## Data Sources (in priority order)

1. **Gmail** — parse transaction emails from Paytm, CRED, Amazon Pay, Uber,
   Blinkit, Zomato, Swiggy, and bank debit alerts (SBI, ICICI, HSBC).
   *Prerequisite: fix Google OAuth first (`tools/google_auth.py`).*

2. **Splitwise** — already connected. When I add a group expense, log Vineet's
   share immediately. Periodically pull expenses others added where Vineet owes.

3. **Manual** — Vineet tells me "spent ₹500 on lunch" via WhatsApp → I log it.

---

## Deduplication

- Each transaction gets a fingerprint: `date + amount + merchant`.
- If a Gmail email matches a Splitwise expense I already logged → skip the
  Gmail entry (Splitwise-sourced entry is more accurate).
- If two emails refer to the same transaction (e.g. Paytm + Blinkit for same
  order) → keep the one with more detail, discard the other.

---

## Splitwise Handling

- When I create a Splitwise expense on Vineet's behalf → log his share
  immediately to the tracker (don't wait for the bank email).
- Mark the corresponding bank transaction (if it appears later) as
  "covered by Splitwise" — don't double-count.
- Settlements received from flatmates → tagged as "reimbursement", not income.

---

## Storage: Google Sheet

*Prerequisite: Google OAuth fixed.*

Single sheet: `Expense Tracker`

| Date | Merchant | Amount | Category | Source | Notes |
|------|----------|--------|----------|--------|-------|

- **Date**: transaction date
- **Merchant**: parsed from email/input
- **Amount**: Vineet's actual share (not group total)
- **Category**: auto-assigned from merchant (see below)
- **Source**: `gmail` / `splitwise` / `manual`
- **Notes**: e.g. "Splitwise: Flat Monthly Jul 2026"

---

## Auto-categorisation (simple keyword map)

| Category     | Merchants / keywords                        |
|--------------|---------------------------------------------|
| Food         | Zomato, Swiggy, restaurant, cafe, dhaba     |
| Groceries    | Blinkit, Zepto, BigBasket, DMart            |
| Transport    | Uber, Ola, Metro, Rapido, fuel              |
| Flat         | Splitwise flat expenses, rent               |
| Shopping     | Amazon, Flipkart, Myntra                    |
| Health       | pharmacy, Apollo, medical                   |
| Entertainment| BookMyShow, Netflix, Spotify                |
| Other        | anything unmatched                          |

Easy to extend — just add rows.

---

## Summaries (pushed via WhatsApp)

- **Every Monday 9 AM**: last week's spend by category + top 3 merchants
- **Every 1st of month**: last month's full breakdown — category totals,
  month-on-month change, top merchants, biggest single expenses

No budget limits — purely analytical ("you spent 40% more on food vs last month").

---

## Files to build

| File | Purpose |
|------|---------|
| `tools/expense_parser.py` | Parse Gmail emails → extract amount/merchant/date |
| `tools/expense_sheet.py` | Read/write Google Sheet |
| `tasks/expense_sync.py` | Daily cron: scan Gmail, dedup, write to sheet |
| `tasks/expense_summary.py` | Weekly + monthly summary generator |
| `.claude/commands/expense.md` | `/expense` slash command for manual log + queries |

Splitwise logging hooks into the existing `tasks/monthly_flat_expenses.py`
— no new file needed there.

---

## Build order

1. Fix Google OAuth (`tools/google_auth.py personal` + `work`)
2. `tools/expense_sheet.py` — sheet read/write
3. `tools/expense_parser.py` — Gmail email parser
4. `tasks/expense_sync.py` + daily cron
5. Splitwise hook in monthly expenses script
6. `tasks/expense_summary.py` + weekly/monthly crons
7. `/expense` slash command

---

## What Vineet needs to do (one-time)

- Fix Google OAuth (tomorrow — reminder set)
- Enable email receipts on Paytm
- Enable email receipts on CRED (usually on by default)
- Enable debit alerts on SBI / ICICI / HSBC
- That's it
