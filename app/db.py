"""Database layer: models, engine, session, startup migration and seeding.

Postgres on Railway (DATABASE_URL from the plugin) or SQLite locally. The
schema is created at start with `create_all`; `schema_version` records which
version is live so a later real migration tool has somewhere to start.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import ROOT, settings

SCHEMA_VERSION = 3  # 2: budget_lines added, suppliers re-shaped; 3: invoices carry chapter + sub_item, sales table removed


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)  # plain text shown in the UI
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Run(Base):
    """One model turn: the record behind the cost cap, the digest and the runbook."""

    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    model: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | refusal | error | aborted | capped
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_names: Mapped[str] = mapped_column(String(200), default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class BudgetLine(Base):
    """One sub-item of the council's 2025 budget (76 rows). Key: chapter + sub_item."""

    __tablename__ = "budget_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter: Mapped[str] = mapped_column(String(60), index=True)
    sub_item: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(60), index=True)
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)  # blank in the source file stays NULL
    allowed_deviation_pct: Mapped[int] = mapped_column(Integer)  # invoice may differ from the supplier's typical amount by this much


class Supplier(Base):
    """A supplier tied to one budget line, with the amount its invoices usually have."""

    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    chapter: Mapped[str] = mapped_column(String(60))
    sub_item: Mapped[str] = mapped_column(String(80))
    payment_terms: Mapped[str] = mapped_column(String(30))
    typical_amount: Mapped[float] = mapped_column(Float)


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier: Mapped[str] = mapped_column(String(120), index=True)
    chapter: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)  # budget line, from the supplier
    sub_item: Mapped[str | None] = mapped_column(String(80), nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="ILS")
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="logged")  # logged | needs_a_look
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)  # over the spec threshold
    source_ref: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)  # the dedup key
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    logged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# ---------------------------------------------------------------------------
# Engine and session
# ---------------------------------------------------------------------------

def make_engine(url: str | None = None):
    url = url or settings.database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Startup: schema, version, seed data
# ---------------------------------------------------------------------------

def init_db(bind=None, data_dir: Path | None = None) -> dict:
    """Create tables, record the schema version, seed reference data if empty."""
    bind = bind or engine
    data_dir = data_dir or (ROOT / "data")
    Base.metadata.create_all(bind)
    report = {"schema_version": SCHEMA_VERSION, "budget_seeded": 0, "suppliers_seeded": 0, "invoices_seeded": 0}
    with Session(bind) as db:
        if db.scalar(select(func.count()).select_from(SchemaVersion)) == 0:
            db.add(SchemaVersion(version=SCHEMA_VERSION))
            db.commit()
        if db.scalar(select(func.count()).select_from(BudgetLine)) == 0:
            report["budget_seeded"] = _seed_budget(db, data_dir / "budget_lines.csv")
        if db.scalar(select(func.count()).select_from(Supplier)) == 0:
            report["suppliers_seeded"] = _seed_suppliers(db, data_dir / "suppliers.csv")
        if db.scalar(select(func.count()).select_from(Invoice)) == 0:
            report["invoices_seeded"] = _seed_invoices(db, data_dir / "invoices_history.csv")
    return report


def _seed_budget(db: Session, path: Path) -> int:
    if not path.exists():
        return 0
    rows = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            amount = r["budget_2025"].strip()
            rows.append(BudgetLine(chapter=r["chapter"].strip(), sub_item=r["sub_item"].strip(),
                                   category=r["category"].strip(), budget=float(amount) if amount else None,
                                   allowed_deviation_pct=int(r["allowed_deviation_pct"])))
    db.add_all(rows)
    db.commit()
    return len(rows)


def _seed_suppliers(db: Session, path: Path) -> int:
    if not path.exists():
        return 0
    rows = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(Supplier(code=r["code"].strip(), name=r["name"].strip(), chapter=r["chapter"].strip(),
                                 sub_item=r["sub_item"].strip(), payment_terms=r["payment_terms"].strip(),
                                 typical_amount=float(r["typical_amount"])))
    db.add_all(rows)
    db.commit()
    return len(rows)


def _seed_invoices(db: Session, path: Path) -> int:
    """The made-up 2025 invoice history (scripts/make_invoice_history.py). Seeded only into an empty table."""
    if not path.exists():
        return 0
    rows = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            amount = r["amount"].strip()
            rows.append(Invoice(supplier=r["supplier"].strip(), chapter=r["chapter"].strip(), sub_item=r["sub_item"].strip(),
                                invoice_number=r["invoice_number"].strip(), amount=float(amount) if amount else None,
                                invoice_date=date.fromisoformat(r["invoice_date"]), status=r["status"].strip(),
                                source_ref=f"history-{r['invoice_number'].strip()}"))
    db.add_all(rows)
    db.commit()
    return len(rows)
