"""Generate data/invoices_history.csv: a made-up 2025 invoice history for the demo.

Reads data/budget_lines.csv and data/suppliers.csv and writes one invoice row
per supplier delivery. Deterministic (fixed seed), so running it twice gives the
same file. The amounts are invented; only the budget and the supplier list are
real. Run from the repo root:

    python scripts/make_invoice_history.py
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
YEAR = 2025
SEED = 2025


def main() -> None:
    rnd = random.Random(SEED)
    budget = {}
    with (DATA / "budget_lines.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            budget[(r["chapter"], r["sub_item"])] = {
                "amount": float(r["budget_2025"]) if r["budget_2025"].strip() else 0.0,
                "dev": int(r["allowed_deviation_pct"]) / 100,
            }
    suppliers = []
    with (DATA / "suppliers.csv").open(encoding="utf-8") as f:
        suppliers = list(csv.DictReader(f))

    by_line: dict[tuple[str, str], list[dict]] = {}
    for s in suppliers:
        by_line.setdefault((s["chapter"], s["sub_item"]), []).append(s)

    rows = []
    for key, group in by_line.items():
        line = budget[key]
        # Most lines end the year a little under budget; a few go over, which makes the data interesting.
        use = rnd.uniform(1.02, 1.15) if rnd.random() < 0.12 else rnd.uniform(0.80, 1.00)
        total_typical = sum(float(s["typical_amount"]) for s in group)
        for s in group:
            typical = float(s["typical_amount"])
            share = typical / total_typical
            target = line["amount"] * use * share
            n = max(1, round(target / typical)) if line["amount"] > 0 else 0
            for i in range(n):
                spread = line["dev"] * 0.7
                amount = round(typical * (1 + rnd.uniform(-spread, spread)))
                base = date(YEAR, 1, 1) + timedelta(days=int((i + 0.5) * 365 / n))
                d = min(date(YEAR, 12, 31), max(date(YEAR, 1, 1), base + timedelta(days=rnd.randint(-6, 6))))
                rows.append({"code": s["code"], "supplier": s["name"], "chapter": key[0], "sub_item": key[1],
                             "invoice_number": f"{s['code']}-{YEAR}-{i + 1:03d}", "invoice_date": d.isoformat(),
                             "amount": amount, "status": "logged"})
    rows.sort(key=lambda r: (r["invoice_date"], r["code"]))
    # A handful of unreadable totals, as the real flow produces: amount blank, status needs_a_look.
    for r in rnd.sample(rows, 6):
        r["amount"] = ""
        r["status"] = "needs_a_look"
    with (DATA / "invoices_history.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "supplier", "chapter", "sub_item", "invoice_number", "invoice_date", "amount", "status"])
        w.writeheader()
        w.writerows(rows)
    spent = sum(float(r["amount"]) for r in rows if r["amount"] != "")
    print(f"{len(rows)} invoices, total {spent:,.0f}")


if __name__ == "__main__":
    main()
