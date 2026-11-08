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

## Open

8. **Run the evals on the real model** · chore · `python -m evals.run --judge` passes at least 80% of the 16 cases; the pass rate is pasted in a PR, and any failing case becomes a prompt fix.
9. **Deploy to Railway** · chore · the web and digest services run from this repository; `/health` returns 200 on the deployed URL; the seed report line shows 76 / 29 / 565.
10. **Run the twelve checks of `spec.md` §7 on the deployed URL** · chore · all twelve pass; the screenshots or notes go in the PR.
11. **Check the phone layout** · chore · the login, chat and invoices panel are usable at 375 px wide.
12. **Calibrate the made-up history** · chore · no budget line sits at several hundred percent only because of its supplier's typical amount (today "הדפסת כתובות ושונות" is at 239%).

## Later (not scheduled)

- Alembic migrations once production data exists.
- Conversation purge at 90 days.
- A month-by-month budget, so "remaining this month" has an answer.
- A real approval step for flagged invoices, done by a person in the app.
