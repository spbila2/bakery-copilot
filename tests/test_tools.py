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


# Electricity (חברת החשמל): typical 20,000, allowed deviation 40% -> usual range 12,000-28,000.
# Test invoices are dated 2026 so the 2025 budget check stays out of the way, except where it is the point.
EL = "חברת החשמל"
Y25 = {"date_from": "2025-01-01", "date_to": "2025-12-31"}


def test_log_invoice_same_source_ref_is_one_row(client, db):
    first = log_invoice(db, supplier=EL, invoice_number="A-1", amount=20000, invoice_date="2026-01-05", source_ref="img_t1")
    second = log_invoice(db, supplier=EL, invoice_number="A-1", amount=20000, invoice_date="2026-01-05", source_ref="img_t1")
    assert first["created"] is True
    assert second["created"] is False and second["reason"] == "duplicate"
    assert second["id"] == first["id"]


def test_log_invoice_same_supplier_and_number_is_one_row(client, db):
    a = log_invoice(db, supplier=EL, invoice_number="7781", amount=20000, invoice_date="2026-01-06", source_ref="img_t2a")
    b = log_invoice(db, supplier="החשמל", invoice_number="7781", amount=20000, invoice_date="2026-01-06", source_ref="img_t2b")
    assert b["created"] is False and b["id"] == a["id"]  # a partial name resolves to the same supplier


def test_known_supplier_inside_range_is_logged_clean(client, db):
    row = log_invoice(db, supplier=EL, invoice_number="C-1", amount="₪20,500", invoice_date="2026-02-01", source_ref="img_t5")
    assert row["status"] == "logged" and row["flagged"] is False and row["flag_reason"] is None
    assert (row["chapter"], row["sub_item"]) == ("מקוואות", "חשמל")
    assert row["expected"] == {"typical": 20000.0, "min": 12000.0, "max": 28000.0, "deviation_pct": 40}


def test_unreadable_amount_goes_to_needs_a_look(client, db):
    row = log_invoice(db, supplier=EL, invoice_number="9", amount=None, invoice_date="2026-02-02", source_ref="img_t3")
    assert row["status"] == "needs_a_look"
    assert row["amount"] is None and row["chapter"] == "מקוואות"
    assert "amount unreadable" in (row["notes"] or "") and "amount_unreadable" in row["flag_reason"]


def test_amount_outside_the_usual_range_is_flagged_not_blocked(client, db):
    high = log_invoice(db, supplier=EL, invoice_number="H1", amount=60000, invoice_date="2026-02-03", source_ref="img_t4")
    assert high["status"] == "logged" and high["flagged"] is True and high["amount"] == 60000.0
    assert "outside_range" in high["flag_reason"]
    low = log_invoice(db, supplier=EL, invoice_number="L1", amount=5000, invoice_date="2026-02-04", source_ref="img_t4b")
    assert low["flagged"] is True and "outside_range" in low["flag_reason"]  # too low is suspicious too


def test_unknown_supplier_goes_to_needs_a_look(client, db):
    row = log_invoice(db, supplier="Negev Eggs", invoice_number="N1", amount=900, invoice_date="2026-02-05", source_ref="img_t6")
    assert row["status"] == "needs_a_look" and row["chapter"] is None
    assert "unknown_supplier" in row["flag_reason"] and "new supplier" in row["notes"]


def test_a_name_that_matches_several_suppliers_is_not_guessed(client, db):
    row = log_invoice(db, supplier="ניקיון", invoice_number="K1", amount=140000, invoice_date="2026-02-06", source_ref="img_t7")
    assert row["status"] == "needs_a_look" and row["chapter"] is None
    assert "ambiguous_supplier" in row["flag_reason"]


def test_invoice_that_breaks_the_annual_budget_is_flagged(client, db):
    # שכר פלוס: חשבות שכר, budget 149,000. Ask the tool what is left, then log one shekel more.
    left = budget_query(db, metric="remaining", group_by="none", chapter="מנהלה", sub_item="חשבות שכר", **Y25)["value"]
    amount = max(1.0, left + 1)
    row = log_invoice(db, supplier="שכר פלוס", invoice_number="B1", amount=amount, invoice_date="2025-12-20", source_ref="img_t8")
    try:
        assert row["status"] == "logged" and row["flagged"] is True
        assert "over_budget" in row["flag_reason"]
    finally:  # a 2025 row would shift the totals other tests compare with the history file
        from app.db import Invoice
        db.query(Invoice).filter_by(source_ref="img_t8").delete()
        db.commit()
    # the same kind of invoice dated outside the budget year is not judged against it
    other = log_invoice(db, supplier="שכר פלוס", invoice_number="B2", amount=12400, invoice_date="2026-03-01", source_ref="img_t9")
    assert "over_budget" not in (other["flag_reason"] or "")


def test_lookup_supplier_partial_match(client, db):
    res = lookup_supplier(db, name="חברת החשמל")
    assert res["known_supplier"] is True
    match = res["matches"][0]
    assert (match["chapter"], match["sub_item"]) == ("מקוואות", "חשמל")
    assert match["typical_amount"] == 20000
    assert (match["allowed_deviation_pct"], match["min_amount"], match["max_amount"]) == (40, 12000.0, 28000.0)
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
