"""budget_query: a structured, read-only view of the budget against logged invoices.

The model does not write SQL. It picks a metric, a grouping and filters; the
backend builds the answer. The tool cannot drop, update or read anything but
budget lines and invoices (least access, as with the bakery's sales_query).

Budget amounts are annual (2025) and are never cut by the date filters; the date
filters apply to invoices only. So "remaining" means: the year's budget minus the
invoices inside the chosen dates.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import BudgetLine, Invoice

METRICS = {"spent", "budget", "remaining", "utilization", "invoice_count"}
GROUP_BY = {"none", "chapter", "sub_item", "category", "supplier", "month"}
# Groupings that have no budget of their own: a supplier or a month is not a budget line.
NO_BUDGET_GROUPS = {"supplier", "month"}
NO_BUDGET_METRICS = {"budget", "remaining", "utilization"}
UNASSIGNED = "לא משויך"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def budget_query(db: Session, *, metric: str = "spent", group_by: str = "none", chapter: str | None = None,
                 sub_item: str | None = None, category: str | None = None, supplier: str | None = None,
                 date_from: str | None = None, date_to: str | None = None, top_n: int = 10) -> dict:
    if metric not in METRICS:
        return {"error": f"unknown metric '{metric}'", "allowed": sorted(METRICS)}
    if group_by not in GROUP_BY:
        return {"error": f"unknown group_by '{group_by}'", "allowed": sorted(GROUP_BY)}
    if group_by in NO_BUDGET_GROUPS and metric in NO_BUDGET_METRICS:
        return {"error": f"'{metric}' cannot be grouped by {group_by}: only budget lines have a budget. "
                         "Group by chapter, sub_item or category, or ask for spent / invoice_count."}
    top_n = max(1, min(int(top_n or 10), 50))
    try:
        d_from, d_to = _parse_date(date_from), _parse_date(date_to)
    except ValueError:
        return {"error": "dates must be YYYY-MM-DD"}

    def like(col, val):
        return func.lower(col).like(f"%{val.lower()}%")

    has_line_filter = bool(chapter or sub_item or category)
    # Budget lines, filtered by what a budget line has.
    line_where = []
    if chapter:
        line_where.append(like(BudgetLine.chapter, chapter))
    if sub_item:
        line_where.append(like(BudgetLine.sub_item, sub_item))
    if category:
        line_where.append(like(BudgetLine.category, category))
    lines = db.scalars(select(BudgetLine).where(*line_where)).all()
    category_of = {(ln.chapter, ln.sub_item): ln.category for ln in db.scalars(select(BudgetLine))}
    wanted = {(ln.chapter, ln.sub_item) for ln in lines}

    # Invoices with an amount, inside the dates, on the wanted budget lines.
    inv_where = [Invoice.amount.is_not(None)]
    if d_from:
        inv_where.append(Invoice.invoice_date >= d_from)
    if d_to:
        inv_where.append(Invoice.invoice_date <= d_to)
    if supplier:
        inv_where.append(like(Invoice.supplier, supplier))
    invoices = [i for i in db.scalars(select(Invoice).where(*inv_where)).all()
                if not has_line_filter or (i.chapter, i.sub_item) in wanted]

    def key_of_line(ln) -> str:
        return {"chapter": ln.chapter, "sub_item": f"{ln.chapter} / {ln.sub_item}", "category": ln.category}.get(group_by, "")

    def key_of_invoice(i) -> str:
        if group_by == "supplier":
            return i.supplier
        if group_by == "month":
            return (i.invoice_date or i.created_at.date()).strftime("%Y-%m")
        if i.chapter is None:
            return UNASSIGNED
        cat = category_of.get((i.chapter, i.sub_item), UNASSIGNED)
        return {"chapter": i.chapter, "sub_item": f"{i.chapter} / {i.sub_item}", "category": cat}.get(group_by, "")

    buckets: dict[str, dict] = {}

    def bucket(k: str) -> dict:
        return buckets.setdefault(k, {"key": k, "budget": 0.0, "spent": 0.0, "invoice_count": 0})

    if group_by == "none":
        bucket("all")
    if group_by not in NO_BUDGET_GROUPS:
        for ln in lines:
            bucket("all" if group_by == "none" else key_of_line(ln))["budget"] += ln.budget or 0.0
    for i in invoices:
        b = bucket("all" if group_by == "none" else key_of_invoice(i))
        b["spent"] += i.amount
        b["invoice_count"] += 1

    has_budget = group_by not in NO_BUDGET_GROUPS
    rows = []
    for b in buckets.values():
        row = {"key": b["key"], "spent": round(b["spent"], 2), "invoice_count": b["invoice_count"]}
        if has_budget:
            row["budget"] = round(b["budget"], 2)
            row["remaining"] = round(b["budget"] - b["spent"], 2)
            row["utilization"] = round(100 * b["spent"] / b["budget"], 1) if b["budget"] else None
        rows.append(row)
    for row in rows:
        row["value"] = row.get(metric)

    filters = {"chapter": chapter, "sub_item": sub_item, "category": category, "supplier": supplier,
               "date_from": str(d_from) if d_from else None, "date_to": str(d_to) if d_to else None}
    note = ("budget is the full 2025 year; date filters apply to invoices only" if has_budget else None)

    if group_by == "none":
        r = rows[0]
        return {"metric": metric, "group_by": "none", "filters": filters, "value": r["value"],
                **{k: r[k] for k in ("spent", "invoice_count", "budget", "remaining", "utilization") if k in r}, "note": note}

    if group_by == "month":
        rows.sort(key=lambda r: r["key"])
        rows = rows[:400]
    else:
        rows.sort(key=lambda r: (r["value"] is None, -(r["value"] or 0)))
        rows = rows[:top_n]
    for row in rows:
        row.pop("value", None)
    return {"metric": metric, "group_by": group_by, "filters": filters, "rows": rows, "row_count": len(rows), "note": note}


def chapters(db: Session) -> list[str]:
    return list(db.scalars(select(BudgetLine.chapter).distinct().order_by(BudgetLine.chapter)))


def invoice_range(db: Session) -> tuple[date | None, date | None]:
    return db.execute(select(func.min(Invoice.invoice_date), func.max(Invoice.invoice_date))).one()
