# Tickets — Council Finance Assistant

The work as tickets a stranger could test. The bakery project this one grew from had 32 tickets (chat, streaming, tools, limits, deploy); they are kept in the git history of the original repository and all of that work is still here. Below: what the council rework changed, one ticket per pull request, and what is still open.

Format: **title** · label · done when.

## Done: the council rework

1. **Load council budget lines and suppliers as seed data** · feature · `budget_lines` has 76 rows summing to ₪22,111,800; `suppliers` has 29, each pointing at exactly one budget line; a blank budget stays NULL. (PR #1)
2. **Replace `sales_query` with `budget_query`** · feature · spent, budget, remaining, utilization and invoice count by chapter, sub-item, category, supplier or month, checked against the CSV files; 565 made-up 2025 invoices; the eval runner no longer wipes the seeded history. (PR #2)
3. **Council invoice rules** · feature · same invoice twice is one row; unknown or ambiguous supplier and unreadable amount go to *needs a look*; an amount outside typical ± allowed deviation, or one that breaks the annual budget, is logged and flagged with its reason. (PR #3)
4. **Hebrew system prompt and council eval cases** · feature · 16 Hebrew cases; the runner checks the chapter and the flag reason of a logged invoice. (PR #4)
5. **Hebrew right-to-left UI with a new logo** · feature · light, colourful theme; all text Hebrew; the invoices panel shows the budget line, status and reasons; tool chips in Hebrew. (PR #5)
6. **Hebrew morning digest with the budget state** · feature · invoices logged, needs a look, flagged with reasons, utilization and lines over budget, chat spend, failed runs. (PR #6)
7. **Council spec, README and deploy settings** · chore · `spec.md` §7 describes the twelve checks for the council; `.railway/railway.ts` deploys this repository, not the original. (PR #7)

## Done after the rework

8. **Run the evals on the real model** · chore · 16 of 16 passed (100%, $0.26, claude-opus-5-5 at medium effort); the row is in `evals/history.csv`.
9. **Deploy to Railway** · chore · web, digest and Postgres run from this repository; `/health` is 200; the seed report shows 76 / 29 / 565.
10. **Run the twelve checks of `spec.md` section 7** · chore · all twelve pass; see [submission-check.md](submission-check.md).
11. **Check the phone layout** · chore · tried on an Android phone; found and fixed a collapsed top bar, a hidden "send" before the photo was ready, buttons too close together, and a stale cached page (PRs 9, 10, 12, 13, 15).
12. **Auto-scroll, camera, keep-alive** · feature · the chat follows the stream, phones get a camera button, photos are shrunk before sending, the stream sends keep-alive lines (PRs 10, 12, 16).
13. **Morning digest by email, Sunday to Thursday** · feature · a Make scenario sends it to Gmail; Sunday's covers Thursday to Saturday; the demo history is not counted (PRs 11, 14).

## Not done, by decision

- Calibrating the made-up history: the line "הדפסת כתובות ושונות" shows 239% of its budget, and the owner chose to leave it.
- Removing the test invoices from the live database: they are made up, so they stay.

## Later (not scheduled)

- Alembic migrations once production data exists.
- Conversation purge at 90 days.
- A month-by-month budget, so "remaining this month" has an answer.
- A real approval step for flagged invoices, done by a person in the app.
