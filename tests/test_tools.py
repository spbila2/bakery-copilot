"""Unit tests: the deterministic parts. Same input, same output, every time."""
import pytest

from app.tools.invoices import log_invoice, lookup_supplier, parse_amount
from app.tools.budget import budget_query


@pytest.mark.parametrize("raw,expected", [
    ("₪1,240.00", 1240.0), ("1 240", 1240.0), ("NIS 85", 85.0), (1240, 1240.0), (99.5, 99.5),
    ("TBD", None), ("", None), (None, None), ("-20", None), ("call us", None),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def test_log_invoice_same_source_ref_is_one_row(client, db):
    first = log_invoice(db, supplier="Levi Flour", invoice_number="A-1", amount=1240, source_ref="img_t1")
    second = log_invoice(db, supplier="Levi Flour", invoice_number="A-1", amount=1240, source_ref="img_t1")
    assert first["created"] is True
    assert second["created"] is False and second["reason"] == "duplicate"
    assert second["id"] == first["id"]


def test_log_invoice_same_supplier_and_number_is_one_row(client, db):
    a = log_invoice(db, supplier="Golan Dairy", invoice_number="7781", amount=500, source_ref="img_t2a")
    b = log_invoice(db, supplier="golan dairy", invoice_number="7781", amount=500, source_ref="img_t2b")
    assert b["created"] is False and b["id"] == a["id"]


def test_unreadable_amount_goes_to_needs_a_look(client, db):
    row = log_invoice(db, supplier="Negev Eggs", invoice_number="9", amount=None, source_ref="img_t3")
    assert row["status"] == "needs_a_look"
    assert row["amount"] is None
    assert "amount unreadable" in (row["notes"] or "")


def test_large_amount_is_flagged_not_blocked(client, db):
    row = log_invoice(db, supplier="Big Oven Ltd", invoice_number="X1", amount="₪6,200", source_ref="img_t4")
    assert row["status"] == "logged" and row["flagged"] is True and row["amount"] == 6200.0


def test_lookup_supplier_partial_match(client, db):
    res = lookup_supplier(db, name="חברת החשמל")
    assert res["known_supplier"] is True
    match = res["matches"][0]
    assert (match["chapter"], match["sub_item"]) == ("מקוואות", "חשמל")
    assert match["typical_amount"] == 20000
    assert lookup_supplier(db, name="nobody-here")["known_supplier"] is False


def test_budget_and_suppliers_are_seeded_from_the_council_files(client, db):
    from sqlalchemy import func, select

    from app.db import BudgetLine, Supplier

    assert db.scalar(select(func.count()).select_from(BudgetLine)) == 76
    assert db.scalar(select(func.count()).select_from(Supplier)) == 29
    assert db.scalar(select(func.sum(BudgetLine.budget))) == 22_111_800
    # a blank amount in the source file stays NULL, not 0
    blank = db.scalar(select(BudgetLine).where(BudgetLine.sub_item == 'ביקורת רו"ח'))
    assert blank.budget is None


def test_every_supplier_points_at_exactly_one_budget_line(client, db):
    from sqlalchemy import func, select

    from app.db import BudgetLine, Supplier

    for s in db.scalars(select(Supplier)).all():
        n = db.scalar(select(func.count()).select_from(BudgetLine).where(
            BudgetLine.chapter == s.chapter, BudgetLine.sub_item == s.sub_item))
        assert n == 1, (s.code, s.chapter, s.sub_item)


# --- budget_query -----------------------------------------------------------------
# Compared against the CSV files directly, not against the database. Other tests log
# invoices into the same database, so the history is isolated with its 2025 dates.

import csv
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
Y25 = {"date_from": "2025-01-01", "date_to": "2025-12-31"}


def _history():
    with (DATA / "invoices_history.csv").open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f)]


def test_budget_total_matches_the_budget_file(client, db):
    res = budget_query(db, metric="budget", group_by="none")
    assert res["value"] == 22_111_800


def test_spent_total_matches_the_history_file(client, db):
    rows = _history()
    expected_spent = sum(float(r["amount"]) for r in rows if r["amount"])
    res = budget_query(db, metric="spent", group_by="none", **Y25)
    assert res["value"] == round(expected_spent, 2)
    assert res["invoice_count"] == sum(1 for r in rows if r["amount"])  # unreadable totals are not counted
    assert res["budget"] == 22_111_800  # date filters never cut the annual budget


def test_group_by_chapter_has_the_eight_chapters_and_sums_up(client, db):
    res = budget_query(db, metric="budget", group_by="chapter", top_n=50)
    # Invoices logged by other tests have no budget line; they show up as their own group, with no budget.
    rows = [r for r in res["rows"] if r["key"] != "לא משויך"]
    assert len(rows) == 8
    assert rows[0]["key"] == "מקוואות" and rows[0]["budget"] == 17_496_800
    assert sum(r["budget"] for r in rows) == 22_111_800


def test_remaining_and_utilization(client, db):
    res = budget_query(db, metric="remaining", group_by="none", chapter="מקוואות", sub_item="חשמל", **Y25)
    assert res["budget"] == 3_497_000
    assert res["remaining"] == round(res["budget"] - res["spent"], 2)
    assert res["utilization"] == round(100 * res["spent"] / res["budget"], 1)


def test_category_grouping_crosses_chapters(client, db):
    res = budget_query(db, metric="budget", group_by="category", top_n=50)
    energy = next(r for r in res["rows"] if r["key"] == "אנרגיה ומים")
    assert energy["budget"] == 9_445_000  # electricity + water + diesel, in two chapters


def test_month_and_supplier_groupings_are_spending_only(client, db):
    months = budget_query(db, metric="spent", group_by="month", **Y25)
    assert 1 <= months["row_count"] <= 12 and months["rows"][0]["key"] == "2025-01"
    assert "budget" not in months["rows"][0]
    err = budget_query(db, metric="remaining", group_by="supplier")
    assert "cannot be grouped by supplier" in err["error"]
    top = budget_query(db, metric="spent", group_by="supplier", top_n=3, **Y25)
    assert top["row_count"] == 3
    assert top["rows"][0]["spent"] >= top["rows"][1]["spent"] >= top["rows"][2]["spent"]


def test_budget_query_rejects_bad_input(client, db):
    assert budget_query(db, metric="nope", group_by="none")["error"].startswith("unknown metric")
    assert budget_query(db, metric="spent", group_by="nope")["error"].startswith("unknown group_by")
    assert budget_query(db, metric="spent", group_by="none", date_from="31/08/2025")["error"] == "dates must be YYYY-MM-DD"
