"""The eval runner's own plumbing, with the fake model: no network, no cost."""
from app.agent import FakeModelClient
from evals import run as evals_run


def test_case_history_reaches_the_model_as_earlier_turns(client):
    fake = FakeModelClient()
    case = {"id": "t", "input": "Do you have airplane tickets?",
            "history": [{"role": "user", "content": "how much does vanilla cost?"},
                        {"role": "assistant", "content": "We usually pay $89 per litre to Madagascar Vanilla Co."}]}
    result = evals_run.run_case(case, fake)
    sent = fake.last_messages
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent[0]["content"] == "how much does vanilla cost?"
    assert "Madagascar Vanilla Co." in sent[1]["content"]
    assert sent[2]["content"][-1]["text"] == "Do you have airplane tickets?"
    assert result["status"] == "ok"


def test_case_without_history_is_a_single_turn(client):
    fake = FakeModelClient()
    evals_run.run_case({"id": "t", "input": "Revenue by branch for August 2026"}, fake)
    assert [m["role"] for m in fake.last_messages] == ["user"]


def test_eval_runner_keeps_the_seeded_invoice_history(client):
    # run_case clears the invoices earlier cases made, but must never wipe the 2025 history.
    from sqlalchemy import func, select

    from app.db import Invoice, SessionLocal

    def history_count():
        with SessionLocal() as db:
            return db.scalar(select(func.count()).select_from(Invoice).where(Invoice.source_ref.like("history-%")))

    before = history_count()
    assert before > 0
    evals_run.run_case({"id": "t", "input": "hello"}, FakeModelClient())
    assert history_count() == before


def test_every_eval_case_is_well_formed():
    # No network: just make sure the cases only name real tools and known expectations.
    import yaml

    from app.tools.registry import TOOL_NAMES

    cases = yaml.safe_load((evals_run.HERE / "cases.yaml").read_text(encoding="utf-8"))
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)) and len(ids) >= 15
    known = {"tools_called", "tools_not_called", "answer_contains_any", "answer_not_contains", "no_invoice_rows",
             "invoice", "invoice_count_for_source_ref"}
    invoice_keys = {"supplier_contains", "status", "flagged", "amount", "chapter", "flag_reason_contains"}
    for c in cases:
        assert c["input"] and c.get("rubric"), c["id"]
        assert set(c.get("expect", {})) <= known, c["id"]
        for t in c["expect"].get("tools_called", []) + c["expect"].get("tools_not_called", []):
            assert t in TOOL_NAMES, (c["id"], t)
        assert set(c["expect"].get("invoice", {})) <= invoice_keys, c["id"]
        for turn in c.get("history", []):
            assert turn["role"] in {"user", "assistant"} and turn["content"], c["id"]


def test_grader_checks_chapter_and_flag_reason():
    case = {"expect": {"invoice": {"status": "needs_a_look", "chapter": None, "flag_reason_contains": "unknown_supplier"}}}
    row = {"supplier": "x", "status": "needs_a_look", "flagged": False, "amount": 1800.0, "chapter": None,
           "flag_reason": "unknown_supplier", "source_ref": "r"}
    ok = {"tools": [], "answer": "", "invoices": [row], "status": "ok"}
    assert evals_run.grade_facts(case, ok) == []
    bad = {**ok, "invoices": [{**row, "chapter": "מקוואות", "flag_reason": "outside_range"}]}
    failures = evals_run.grade_facts(case, bad)
    assert any("flag_reason" in f for f in failures) and any("chapter" in f for f in failures)
