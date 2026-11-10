"""The morning digest: yesterday and the state of the budget, in a few Hebrew lines.

Runs as a Railway cron service (`python -m app.digest`, schedule in README.md)
or through POST /internal/digest. It only reads; the rows it reports were
written by the chat turns during the day.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from .config import settings
from .db import Invoice, Message, Run, SessionLocal, init_db
from .tools.budget import budget_query
from .tools.invoices import BUDGET_YEAR, FLAG_REASONS_HE

DAYS_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]  # date.weekday(): Monday is 0


def _local_bounds(day: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo(settings.timezone)
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    return start, end


def _reasons(inv: Invoice) -> str:
    return ", ".join(FLAG_REASONS_HE.get(k, k) for k in (inv.flag_reason or "").split(",") if k)


def _over_budget_line(db: Session) -> str:
    """The year's budget state: overall utilization and the lines already past their budget."""
    year = {"date_from": f"{BUDGET_YEAR}-01-01", "date_to": f"{BUDGET_YEAR}-12-31"}
    total = budget_query(db, metric="utilization", group_by="none", **year)
    rows = budget_query(db, metric="utilization", group_by="sub_item", top_n=50, **year)["rows"]
    over = [r for r in rows if r.get("utilization") is not None and r["utilization"] > 100]
    overall = f"{total['utilization']:.1f}%" if total.get("utilization") is not None else "אין נתון"
    line = f"תקציב {BUDGET_YEAR}: ניצול כולל {overall} · סעיפים שחרגו מהתקציב: {len(over)}"
    if over:
        line += " — " + "; ".join(f"{r['key']} ({r['utilization']:.0f}%)" for r in over[:3])
    return line


def digest_period(today: date) -> tuple[date, date]:
    """The days a morning digest covers: yesterday. The digest is sent Sunday to Thursday, so Sunday's covers
    the stretch since the last one, Thursday to Saturday, and nothing falls between two digests."""
    if today.weekday() == 6:  # Sunday
        return today - timedelta(days=3), today - timedelta(days=1)
    yesterday = today - timedelta(days=1)
    return yesterday, yesterday


def build_digest(db: Session, day: date | None = None, last_day: date | None = None) -> str:
    """The digest for `day` (through `last_day`, if given); with no day, for the period that is due today."""
    if day is None:
        day, last_day = digest_period(datetime.now(ZoneInfo(settings.timezone)).date())
    last_day = last_day or day
    start, end = _local_bounds(day)[0], _local_bounds(last_day)[1]

    # The seeded demo history (source_ref "history-...") is not part of any day's work, whenever it was loaded.
    real = or_(Invoice.source_ref.is_(None), ~Invoice.source_ref.like("history-%"))
    invoices = db.scalars(select(Invoice).where(Invoice.created_at >= start, Invoice.created_at < end, real)
                          .order_by(Invoice.created_at)).all()
    logged = [i for i in invoices if i.status == "logged"]
    needs = [i for i in invoices if i.status == "needs_a_look"]
    flagged = [i for i in invoices if i.flagged]
    total = sum(i.amount or 0 for i in logged)

    messages = db.scalar(select(func.count()).select_from(Message)
                         .where(Message.role == "user", Message.created_at >= start, Message.created_at < end)) or 0
    runs = db.execute(select(func.count(Run.id), func.coalesce(func.sum(Run.cost_usd), 0.0),
                             func.sum(case((Run.status != "ok", 1), else_=0)))
                      .where(Run.created_at >= start, Run.created_at < end)).one()
    run_count, cost, not_ok = int(runs[0] or 0), float(runs[1] or 0.0), int(runs[2] or 0)

    def who(i: Invoice) -> str:
        return f"{i.supplier} ({i.invoice_number or 'ללא מספר'})"

    if day == last_day:
        when = f"יום {DAYS_HE[day.weekday()]} {day.strftime('%d.%m.%Y')}"
    else:
        when = f"מיום {DAYS_HE[day.weekday()]} {day.strftime('%d.%m')} עד יום {DAYS_HE[last_day.weekday()]} {last_day.strftime('%d.%m.%Y')}"
    lines = [f"עוזר הכספים · סיכום בוקר · {when}",
             f"חשבוניות שנרשמו: {len(logged)} · סה״כ ₪{total:,.0f}",
             f"דורשות בדיקה: {len(needs)}" + (" — " + "; ".join(f"{who(i)}: {_reasons(i) or 'לבדיקה'}" for i in needs[:5]) if needs else ""),
             f"חריגות: {len(flagged)}" + (" — " + "; ".join(f"{who(i)} ₪{i.amount or 0:,.0f}: {_reasons(i) or 'לבדיקה'}" for i in flagged[:5]) if flagged else ""),
             _over_budget_line(db),
             f"צ'אט: {messages} הודעות · {run_count} הרצות מודל · ${cost:.2f} מתוך ${settings.daily_cap_usd:.2f} ביום",
             f"הרצות שנכשלו: {not_ok}" + (" — לבדוק את טבלת runs ואת runbook.md" if not_ok else "")]
    return "\n".join(lines)


def send_digest(text: str) -> bool:
    """POST {"text": ...} to DIGEST_WEBHOOK_URL (Slack-compatible). Returns False when no URL is set."""
    if not settings.digest_webhook_url:
        return False
    import httpx

    r = httpx.post(settings.digest_webhook_url, json={"text": text}, timeout=15)
    r.raise_for_status()
    return True


def main() -> None:
    init_db()
    with SessionLocal() as db:
        body = build_digest(db)
    print(body)
    sent = send_digest(body)
    print(f"\n[sent to webhook: {sent}]")


if __name__ == "__main__":
    main()
