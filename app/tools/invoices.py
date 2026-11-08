"""log_invoice and lookup_supplier: the two writes-and-reads around invoices.

Rules from spec.md, enforced here and not in the prompt:
- the same invoice twice makes one row (source_ref, or supplier + number);
- an unreadable amount is never guessed: the row goes to "needs_a_look";
- a supplier that is not on the list (or matches several) goes to "needs_a_look";
- an amount outside the supplier's usual range is logged and flagged;
- an invoice that takes its budget line over the year's budget is logged and flagged.
Nothing here pays, approves or changes an existing row.

The range is the supplier's typical amount +/- the allowed deviation of its budget line.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import BudgetLine, Invoice, Supplier

BUDGET_YEAR = 2025  # the budget file covers one year; the over-budget check applies to invoices of that year
# Why a row was flagged or needs a look, in words for people (the UI and the digest share these).
FLAG_REASONS_HE = {
    "outside_range": "מחוץ לטווח הרגיל של הספק", "over_budget": "חריגה מהתקציב השנתי", "unknown_supplier": "ספק לא מוכר",
    "ambiguous_supplier": "שם ספק דו-משמעי", "amount_unreadable": "סכום לא קריא",
}
_AMOUNT_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def parse_amount(text: str | float | int | None) -> float | None:
    """'₪1,240.00' -> 1240.0; '1 240' -> 1240.0; 'TBD' -> None; negatives -> None."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text) if text > 0 else None
    cleaned = str(text).replace("₪", "").replace("NIS", "").replace("ILS", "").replace(" ", "")
    m = _AMOUNT_RE.search(cleaned)
    if not m:
        return None
    try:
        value = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _find_suppliers(db: Session, name: str) -> list[Supplier]:
    needle = (name or "").strip().lower()
    if not needle:
        return []
    rows = db.scalars(select(Supplier).where(func.lower(Supplier.name).like(f"%{needle}%"))).all()
    if not rows:
        # second chance: any word of the name
        for word in [w for w in re.split(r"\W+", needle) if len(w) > 3]:
            rows = db.scalars(select(Supplier).where(func.lower(Supplier.name).like(f"%{word}%"))).all()
            if rows:
                break
    return list(rows)


def _line_of(db: Session, supplier: Supplier) -> BudgetLine | None:
    return db.scalar(select(BudgetLine).where(BudgetLine.chapter == supplier.chapter, BudgetLine.sub_item == supplier.sub_item))


def _range(supplier: Supplier, line: BudgetLine | None) -> tuple[float, float, int]:
    dev = line.allowed_deviation_pct if line else 0
    return (round(supplier.typical_amount * (1 - dev / 100), 2), round(supplier.typical_amount * (1 + dev / 100), 2), dev)


def log_invoice(db: Session, *, supplier: str | None, invoice_number: str | None = None, amount=None,
                currency: str = "ILS", invoice_date: str | None = None, source_ref: str | None = None,
                notes: str | None = None, logged_by: int | None = None) -> dict:
    supplier_text = (supplier or "").strip()
    invoice_number = (invoice_number or "").strip() or None
    source_ref = (source_ref or "").strip() or None
    amount_value = parse_amount(amount)
    when = _parse_date(invoice_date)

    # Which supplier is this? One match is a match; none or several is a question for a person.
    candidates = _find_suppliers(db, supplier_text)
    exact = [c for c in candidates if c.name.lower() == supplier_text.lower()]
    match = exact[0] if exact else (candidates[0] if len(candidates) == 1 else None)
    canonical = match.name if match else supplier_text

    # Idempotency: the same invoice twice is one row (Lesson 5, run-it-twice).
    existing = None
    if source_ref:
        existing = db.scalar(select(Invoice).where(Invoice.source_ref == source_ref))
    if existing is None and canonical and invoice_number:
        existing = db.scalar(select(Invoice).where(func.lower(Invoice.supplier) == canonical.lower(),
                                                   Invoice.invoice_number == invoice_number))
    if existing is not None:
        return {"created": False, "reason": "duplicate", **_row(existing)}

    problems: list[str] = []   # make the row "needs_a_look": a person must read or decide
    reasons: list[str] = []    # machine-readable, stored in flag_reason
    flags: list[str] = []      # row is logged, but flagged for review
    line = None
    if not supplier_text:
        problems.append("supplier missing")
        reasons.append("unknown_supplier")
    elif match is None and candidates:
        problems.append("several suppliers match: " + ", ".join(c.name for c in candidates[:4]))
        reasons.append("ambiguous_supplier")
    elif match is None:
        problems.append("supplier not on the list: new supplier for review")
        reasons.append("unknown_supplier")
    if amount_value is None:
        problems.append("amount unreadable")
        reasons.append("amount_unreadable")

    if match is not None:
        line = _line_of(db, match)
        if amount_value is not None:
            low, high, dev = _range(match, line)
            if not low <= amount_value <= high:
                flags.append(f"outside the usual range {low:,.0f}–{high:,.0f} (typical {match.typical_amount:,.0f} ±{dev}%)")
                reasons.append("outside_range")
            in_budget_year = when is None or when.year == BUDGET_YEAR
            if line is not None and line.budget is not None and in_budget_year:
                spent = db.scalar(select(func.coalesce(func.sum(Invoice.amount), 0.0)).where(
                    Invoice.chapter == match.chapter, Invoice.sub_item == match.sub_item,
                    func.coalesce(func.strftime("%Y", Invoice.invoice_date) if db.bind.dialect.name == "sqlite"
                                  else func.to_char(Invoice.invoice_date, "YYYY"), str(BUDGET_YEAR)) == str(BUDGET_YEAR)))
                if spent + amount_value > line.budget:
                    flags.append(f"takes {match.chapter} / {match.sub_item} over its budget "
                                 f"({spent + amount_value:,.0f} of {line.budget:,.0f})")
                    reasons.append("over_budget")

    status = "needs_a_look" if problems else "logged"
    inv = Invoice(
        supplier=canonical or "unknown", chapter=match.chapter if match else None, sub_item=match.sub_item if match else None,
        invoice_number=invoice_number, amount=amount_value, currency=(currency or "ILS").upper()[:3],
        invoice_date=when, status=status, flagged=bool(flags), flag_reason=",".join(reasons) or None,
        source_ref=source_ref, notes="; ".join(filter(None, [notes, *problems, *flags])) or None, logged_by=logged_by,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    out = {"created": True, "reason": None, **_row(inv)}
    if match is not None:
        low, high, dev = _range(match, line)
        out["expected"] = {"typical": match.typical_amount, "min": low, "max": high, "deviation_pct": dev}
    return out


def lookup_supplier(db: Session, *, name: str) -> dict:
    rows = _find_suppliers(db, name)
    matches = []
    for r in rows:
        low, high, dev = _range(r, _line_of(db, r))
        matches.append({"supplier": r.name, "code": r.code, "chapter": r.chapter, "sub_item": r.sub_item,
                        "payment_terms": r.payment_terms, "typical_amount": r.typical_amount,
                        "allowed_deviation_pct": dev, "min_amount": low, "max_amount": high})
    return {"matches": matches, "known_supplier": bool(matches)}


def recent_invoices(db: Session, limit: int = 50) -> list[dict]:
    rows = db.scalars(select(Invoice).order_by(Invoice.created_at.desc()).limit(limit)).all()
    return [_row(r) for r in rows]


def _row(inv: Invoice) -> dict:
    return {
        "id": inv.id, "supplier": inv.supplier, "chapter": inv.chapter, "sub_item": inv.sub_item,
        "invoice_number": inv.invoice_number, "amount": inv.amount,
        "currency": inv.currency, "invoice_date": str(inv.invoice_date) if inv.invoice_date else None,
        "status": inv.status, "flagged": inv.flagged, "flag_reason": inv.flag_reason,
        "source_ref": inv.source_ref, "notes": inv.notes,
        "created_at": inv.created_at.isoformat(timespec="seconds") if inv.created_at else None,
    }
