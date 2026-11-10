# Submission check: the twelve checks of spec.md section 7

Run on 2026-11-10 against the live site, https://web-production-618ce.up.railway.app, and the repository
https://github.com/spbila2/council-finance-assistant. "By hand" means the project owner did it in the browser,
on a phone and on a desktop; "eval" is a case of `evals/cases.yaml` run on the real model (16 of 16 passed);
"live" is a request made to the deployed site.

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Open the URL, sign in, see an empty Hebrew chat, right to left, with the logo | Pass | By hand; the page is `lang="he" dir="rtl"` (live) |
| 2 | A wrong password is refused | Pass | Live: `POST /api/login` with a wrong password returns 401 "Wrong password." |
| 3 | "מה התקציב לכל פרק ב-2025?" lists the eight chapters, total ₪22,111,800 | Pass | By hand; eval `budget_by_chapter` |
| 4 | "כמה נשאר בתקציב החשמל של המקוואות?" gives budget, spent and remaining | Pass | By hand; eval `remaining_electricity_mikvaot` |
| 5 | A clear invoice from a known supplier is logged, with its budget line, no flag | Pass | By hand; eval `invoice_clear` |
| 6 | The same invoice again is still one row and the reply says it exists | Pass | By hand; eval `invoice_duplicate`; unit tests |
| 7 | An unreadable total is logged as *needs a look* with no amount | Pass | Eval `invoice_unclear_amount`; unit tests |
| 8 | An amount far from the supplier's usual one is logged and flagged, with the reason | Pass | By hand (a ₪95,000 electricity invoice, also in the morning digest); eval `invoice_outside_range` |
| 9 | An unknown supplier is marked *needs a look* with no budget line | Pass | Eval `invoice_unknown_supplier`; real-model run with a drawn invoice image |
| 10 | Deleting and paying are refused, with a pointer to the finance manager | Pass | By hand (delete); evals `refuse_delete` and `refuse_payment` |
| 11 | The 31st message within an hour is refused with a clear message | Pass (automated only) | `tests/test_limits.py`; not repeated live, because it would take 31 real model calls |
| 12 | `/health` is 200 on the deployed URL, the digest arrives, tests and evals pass | Pass | Live `/health` 200 (`provider: anthropic`, `db: postgres`); the digest email arrived in Gmail; `pytest -q` 66 passed; evals 16/16 (100%, $0.26) |

## Also checked

- The live site answers 401 without a session on `/api/chat` and `/api/invoices`, and on `/internal/digest` without the cron secret.
- The page and its files are served `no-cache`, and the asset URLs carry a version, so a phone loads a new deploy.
- The morning digest is emailed Sunday to Thursday at 06:30 Israel time (winter) through a Make scenario to Gmail;
  Sunday's covers Thursday to Saturday.
- Photos from a phone camera are shrunk in the browser (1600 px JPEG) before they are sent.

## What is not covered

- The assistant never approves or pays anything; there is no approval step in this version (spec.md section 3).
- The invoice history is made up (565 invoices for 2025); only the budget file is real.
- Real photographed invoices were tried by hand only a few times; the unreadable and unknown-supplier cases were checked
  on the real model with a drawn image, not a photograph.
