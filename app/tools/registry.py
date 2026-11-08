"""Tool definitions the model sees, and the dispatcher that runs them."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from . import budget, invoices

TOOLS: list[dict[str, Any]] = [
    {
        "name": "budget_query",
        "description": (
            "Read-only query over the council's 2025 budget and the logged supplier invoices. "
            "Use it for any question about how much was spent, what is left in the budget, utilization, "
            "invoice counts, or how spending splits by chapter, sub-item, category, supplier or month. "
            "The budget is the full year; date filters (YYYY-MM-DD) apply to invoices only. "
            "Never guess numbers: if the answer needs data, call this tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "enum": sorted(budget.METRICS), "description": "spent (ILS), budget (ILS, annual), remaining (budget minus spent), utilization (percent of budget spent) or invoice_count."},
                "group_by": {"type": "string", "enum": sorted(budget.GROUP_BY), "description": "none for one total; chapter/sub_item/category for a split by budget; supplier or month for spending only (no budget exists per supplier or month)."},
                "chapter": {"type": "string", "description": "substring match on the budget chapter (e.g. מקוואות, קבורה, כשרות, מנהלה)"},
                "sub_item": {"type": "string", "description": "substring match on the sub-item (e.g. חשמל, ביטוח, ניקיון)"},
                "category": {"type": "string", "description": "substring match on the category (e.g. אנרגיה ומים, אחזקה וניקיון)"},
                "supplier": {"type": "string", "description": "substring match on the supplier name"},
                "date_from": {"type": "string", "description": "inclusive start date YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "inclusive end date YYYY-MM-DD"},
                "top_n": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
            "required": ["metric", "group_by"],
            "additionalProperties": False,
        },
    },
    {
        "name": "lookup_supplier",
        "description": "Look up a supplier by (partial) name in the council's supplier list. Returns the canonical name, the budget line (chapter and sub-item), the payment terms and the usual invoice amount. Call it before logging an invoice to normalise the supplier name.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "supplier name as written on the invoice"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "log_invoice",
        "description": (
            "Record one supplier invoice as one row. Pass the fields exactly as read from the document; "
            "pass amount as null if you cannot read it with confidence, and the row will be marked needs_a_look. "
            "Always pass source_ref (the image reference given in the message) so the same invoice is never logged twice. "
            "Never call this to modify or delete an existing row."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "supplier": {"type": "string"},
                "invoice_number": {"type": ["string", "null"]},
                "amount": {"type": ["number", "null"], "description": "total amount, numbers only; null if unreadable"},
                "currency": {"type": "string", "default": "ILS"},
                "invoice_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "source_ref": {"type": ["string", "null"], "description": "the image reference from the message, e.g. img_8f3a2c"},
                "notes": {"type": ["string", "null"]},
            },
            "required": ["supplier", "amount"],
            "additionalProperties": False,
        },
    },
]

TOOL_NAMES = {t["name"] for t in TOOLS}
MAX_RESULT_CHARS = 12000


def execute(name: str, tool_input: dict[str, Any], db: Session, *, user_id: int | None = None) -> str:
    """Run one tool and return its result as a JSON string for the model."""
    try:
        if name == "budget_query":
            result = budget.budget_query(db, **_clean(tool_input))
        elif name == "lookup_supplier":
            result = invoices.lookup_supplier(db, name=str(tool_input.get("name", "")))
        elif name == "log_invoice":
            result = invoices.log_invoice(db, logged_by=user_id, **_clean(tool_input))
        else:
            result = {"error": f"unknown tool '{name}'"}
    except Exception as exc:  # the loop must survive a bad input; the model sees the error
        result = {"error": f"{type(exc).__name__}: {exc}"}
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + '... (truncated)"}'
    return text


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}
