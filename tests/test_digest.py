"""The morning digest: Hebrew, six-ish lines, numbers from the rows."""
import csv
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import pytest

from app.db import Invoice
from app.digest import build_digest, digest_period

DATA = Path(__file__).resolve().parent.parent / "data"
DAY = date(2030, 1, 15)  # a day no other test writes to


@pytest.fixture
def day_rows(db):
    at = datetime(2030, 1, 15, 10, 0)  # 12:00 in Jerusalem, so the same local day
    rows = [
        Invoice(supplier="חברת החשמל", chapter="מקוואות", sub_item="חשמל", invoice_number="D-1", amount=20000.0,
                status="logged", source_ref="dg1", created_at=at),
        Invoice(supplier="חברת החשמל", chapter="מקוואות", sub_item="חשמל", invoice_number="D-2", amount=90000.0,
                status="logged", flagged=True, flag_reason="outside_range", source_ref="dg2", created_at=at),
        Invoice(supplier="מאפיית הדגל", invoice_number=None, amount=1800.0, status="needs_a_look",
                flag_reason="unknown_supplier", source_ref="dg3", created_at=at),
    ]
    db.add_all(rows)
    db.commit()
    yield rows
    db.query(Invoice).filter(Invoice.source_ref.in_(["dg1", "dg2", "dg3"])).delete(synchronize_session=False)
    db.commit()


def test_digest_is_in_hebrew_and_counts_the_day(client, db, day_rows):
    text = build_digest(db, DAY)
    lines = text.split("\n")
    assert lines[0] == "עוזר הכספים · סיכום בוקר · יום שלישי 15.01.2030"
    assert lines[1] == "חשבוניות שנרשמו: 2 · סה״כ ₪110,000"
    assert lines[2].startswith("דורשות בדיקה: 1") and "מאפיית הדגל (ללא מספר)" in lines[2] and "ספק לא מוכר" in lines[2]
    assert lines[3].startswith("חריגות: 1") and "₪90,000" in lines[3] and "מחוץ לטווח הרגיל של הספק" in lines[3]
    assert "Bakery" not in text and "5,000" not in text


def test_digest_reports_the_lines_over_budget(client, db):
    # Oracle: the budget and history files, summed by hand.
    budget, spent = {}, defaultdict(float)
    with (DATA / "budget_lines.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            budget[(r["chapter"], r["sub_item"])] = float(r["budget_2025"] or 0)
    with (DATA / "invoices_history.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["amount"]:
                spent[(r["chapter"], r["sub_item"])] += float(r["amount"])
    over = sum(1 for k, b in budget.items() if b and spent[k] > b)
    assert over >= 1  # the generator makes a few lines go over, so this line is worth reading
    line = build_digest(db, DAY).split("\n")[4]
    assert line.startswith("תקציב 2025: ניצול כולל") and f"סעיפים שחרגו מהתקציב: {over}" in line


def test_an_empty_day_still_reads_cleanly(client, db):
    lines = build_digest(db, date(2031, 6, 1)).split("\n")
    assert lines[1] == "חשבוניות שנרשמו: 0 · סה״כ ₪0"
    assert lines[2] == "דורשות בדיקה: 0" and lines[3] == "חריגות: 0"
    assert lines[-1] == "הרצות שנכשלו: 0"


def test_seeded_history_is_not_reported_as_a_days_work(client, db):
    # The history rows are stamped with the day they were loaded; the digest must not count them as that day's invoices.
    at = datetime(2032, 3, 1, 10, 0)
    row = Invoice(supplier="חברת החשמל", chapter="מקוואות", sub_item="חשמל", invoice_number="H-1", amount=999999.0,
                  status="logged", source_ref="history-H-1", created_at=at)
    db.add(row)
    db.commit()
    try:
        assert build_digest(db, date(2032, 3, 1)).split("\n")[1] == "חשבוניות שנרשמו: 0 · סה״כ ₪0"
    finally:
        db.query(Invoice).filter(Invoice.source_ref == "history-H-1").delete()
        db.commit()


def test_a_digest_covers_yesterday_and_sunday_covers_thursday_to_saturday(client):
    assert digest_period(date(2030, 1, 7)) == (date(2030, 1, 6), date(2030, 1, 6))  # Monday: Sunday
    assert digest_period(date(2030, 1, 10)) == (date(2030, 1, 9), date(2030, 1, 9))  # Thursday: Wednesday
    assert digest_period(date(2030, 1, 6)) == (date(2030, 1, 3), date(2030, 1, 5))  # Sunday: Thursday to Saturday


def test_a_multi_day_digest_counts_every_day_in_the_period(client, db):
    def row(ref, day, amount):
        return Invoice(supplier="חברת החשמל", chapter="מקוואות", sub_item="חשמל", invoice_number=ref, amount=amount,
                       status="logged", source_ref=ref, created_at=datetime(2030, 1, day, 10, 0))

    rows = [row("mp-wed", 2, 1000.0), row("mp-thu", 3, 2000.0), row("mp-fri", 4, 3000.0), row("mp-sat", 5, 4000.0), row("mp-sun", 6, 5000.0)]
    db.add_all(rows)
    db.commit()
    try:
        lines = build_digest(db, date(2030, 1, 3), date(2030, 1, 5)).split("\n")
        assert lines[0] == "עוזר הכספים · סיכום בוקר · מיום חמישי 03.01 עד יום שבת 05.01.2030"
        assert lines[1] == "חשבוניות שנרשמו: 3 · סה״כ ₪9,000"  # Thursday, Friday, Saturday; not Wednesday, not Sunday
    finally:
        db.query(Invoice).filter(Invoice.source_ref.like("mp-%")).delete(synchronize_session=False)
        db.commit()
