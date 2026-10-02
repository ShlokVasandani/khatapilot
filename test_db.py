"""Offline tests for db.py. Run with:  python test_db.py   (no API key needed)."""

import os
import tempfile
from datetime import date, timedelta

import db

TODAY = date(2026, 10, 2)


def fresh():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    conn = db.connect(path)
    db.seed_demo(conn, TODAY)
    return conn


def ex(**kw):
    base = {"intent": "other", "party": None, "items": [], "amount_inr": None,
            "due_date": None, "due_date_text": None, "direction": None, "notes": None}
    base.update(kw)
    return base


def test_order_reduces_stock_and_flags_shortage():
    c = fresh()
    r = db.apply_extraction(c, "m", ex(intent="order", party="Gupta store",
                                       items=[{"name": "Sugar", "quantity": 25, "unit": "kg"}]))
    assert r["status"] == "recorded" and "STOCK SHORT" not in r["detail"]
    assert c.execute("SELECT stock_qty FROM items WHERE name='sugar'").fetchone()[0] == 35
    assert any(row["name"] == "sugar" for row in db.low_stock(c))  # 35 <= 40
    r = db.apply_extraction(c, "m", ex(intent="order",
                                       items=[{"name": "sugar", "quantity": 50, "unit": "kg"}]))
    assert "STOCK SHORT" in r["detail"]


def test_invalid_extractions_go_to_review():
    c = fresh()
    assert db.apply_extraction(c, "m", ex(intent=None))["status"] == "review"
    assert db.apply_extraction(c, "m", ex(intent="order", items=[{"name": "tel", "quantity": -3}]))["status"] == "review"
    assert db.apply_extraction(c, "m", ex(intent="payment_promise", party="X", amount_inr=100,
                                          due_date="parso"))["status"] == "review"
    assert db.apply_extraction(c, "m", ex(intent="payment_received", amount_inr=12000,
                                          direction="customer_owes_us"))["status"] == "review"  # no payer
    assert db.apply_extraction(c, "m", ex(intent="complaint"))["status"] == "review"
    assert len(db.pending_review(c)) == 5


def test_promise_updates_existing_due_instead_of_duplicating():
    c = fresh()
    before = c.execute("SELECT COUNT(*) FROM dues").fetchone()[0]
    r = db.apply_extraction(c, "m", ex(intent="payment_promise", party="sharma ji", amount_inr=4500,
                                       due_date="2026-10-04", direction="customer_owes_us"))
    assert r["status"] == "recorded"
    assert c.execute("SELECT COUNT(*) FROM dues").fetchone()[0] == before
    assert c.execute("SELECT due_date FROM dues d JOIN parties p ON p.id=d.party_id "
                     "WHERE p.name_key='sharma ji'").fetchone()[0] == "2026-10-04"


def test_payment_pays_oldest_due_first_and_keeps_leftover():
    c = fresh()
    r = db.apply_extraction(c, "m", ex(intent="payment_received", party="Kapoor traders",
                                       amount_inr=5000, direction="customer_owes_us"))
    assert r["status"] == "recorded"
    assert db.open_totals(c)["customer_owes_us"] == 12000 - 5000 + 4500
    r = db.apply_extraction(c, "m", ex(intent="payment_received", party="Kapoor traders",
                                       amount_inr=9000, direction="customer_owes_us"))
    assert "unallocated" in r["detail"]  # only 7000 was left
    assert db.open_totals(c)["customer_owes_us"] == 4500


def test_overdue_and_supplier_side():
    c = fresh()
    overdue = {r["party"] for r in db.overdue_dues(c, TODAY)}
    assert overdue == {"Kapoor traders", "Sharma ji"}  # Mehta is due in the future
    r = db.apply_extraction(c, "m", ex(intent="payment_received", party="Mehta wholesale",
                                       amount_inr=3000, direction="we_owe_supplier"))
    assert r["status"] == "recorded"
    assert db.open_totals(c)["we_owe_supplier"] == 5000


def test_supplier_direction_inferred_from_party_kind():
    c = fresh()
    # the model gave no direction, but Mehta is a known supplier
    db.apply_extraction(c, "m", ex(intent="payment_promise", party="Mehta wholesale",
                                   amount_inr=2000, due_date="2026-10-09"))
    assert db.open_totals(c)["we_owe_supplier"] == 10000
    assert db.open_totals(c)["customer_owes_us"] == 16500  # untouched
    db.apply_extraction(c, "m", ex(intent="payment_made", party="Mehta wholesale", amount_inr=3000))
    assert db.open_totals(c)["we_owe_supplier"] == 7000
    # a payment with no direction to a known supplier also settles the supplier side
    db.apply_extraction(c, "m", ex(intent="payment_received", party="Mehta wholesale", amount_inr=1000))
    assert db.open_totals(c)["we_owe_supplier"] == 6000
    assert db.open_totals(c)["customer_owes_us"] == 16500


def test_known_customer_beats_wrong_model_direction():
    c = fresh()
    # the model mislabels a customer's payment as "we paid a supplier"
    r = db.apply_extraction(c, "m", ex(intent="payment_made", party="Kapoor traders",
                                       amount_inr=5000, direction="we_owe_supplier"))
    assert "5000 applied" in r["detail"]
    assert db.open_totals(c)["customer_owes_us"] == 12000 - 5000 + 4500
    assert db.open_totals(c)["we_owe_supplier"] == 8000  # supplier side untouched


def test_typo_in_direction_is_forgiven():
    c = fresh()
    r = db.apply_extraction(c, "m", ex(intent="payment_received", party="Kapoor traders",
                                       amount_inr=4000, direction="customer_ows_us"))
    assert r["status"] == "recorded" and "4000 applied" in r["detail"]


def test_narration_number_guard_and_fallback():
    import narrate
    c = fresh()
    b = db.briefing(c, TODAY)
    facts = narrate._facts_for_model(b)
    assert narrate.numbers_ok("Kapoor traders ke Rs 12,000 overdue hain, 3 din me.", facts) == []
    assert narrate.numbers_ok("Rs 15,000 collect karna hai", facts) == [15000.0]

    class Fake:
        def __init__(self, text): self.text = text
        @property
        def chat(self): return self
        @property
        def completions(self): return self
        def create(self, **kw):
            m = type("M", (), {"content": self.text})
            return type("R", (), {"choices": [type("C", (), {"message": m})]})

    good, src = narrate.narrate(b, client=Fake("<think>x</think>Collect Rs 16,500 today."), model="m")
    assert src == "nemotron" and good == "Collect Rs 16,500 today."
    bad, src = narrate.narrate(b, client=Fake("Collect Rs 99,999 today."), model="m")
    assert src == "fallback" and "DAILY BRIEFING" in bad


def test_drafts_generate_dedupe_and_approval():
    import drafts
    c = fresh()
    db.apply_extraction(c, "m", ex(intent="order", party="Gupta store",
                                   items=[{"name": "Sugar", "quantity": 25, "unit": "kg"}]))  # sugar now low
    ids = drafts.generate(c, TODAY, use_llm=False)
    kinds = sorted(r["kind"] for r in c.execute("SELECT kind FROM drafts"))
    assert kinds.count("payment_reminder") == 2 and kinds.count("reorder") == 1  # Kapoor, Sharma; one supplier order
    assert not any(r["party"] == "Mehta wholesale" and r["kind"] != "reorder"
                   for r in c.execute("SELECT party, kind FROM drafts"))  # never dun a supplier
    assert drafts.generate(c, TODAY, use_llm=False) == []                  # no duplicates
    kap = c.execute("SELECT body FROM drafts WHERE party='Kapoor traders'").fetchone()["body"]
    assert "12,000" in kap
    drafts.set_status(c, ids[0], "approved")
    assert len(drafts.pending(c)) == len(ids) - 1
    drafts.edit(c, ids[1], "Namaste, kal tak bhej dena")
    assert c.execute("SELECT source FROM drafts WHERE id=?", (ids[1],)).fetchone()[0] == "owner"


def test_draft_wording_guard():
    import drafts

    class Fake:
        def __init__(self, text): self.text = text
        @property
        def chat(self): return self
        @property
        def completions(self): return self
        def create(self, **kw):
            m = type("M", (), {"content": self.text})
            return type("R", (), {"choices": [type("C", (), {"message": m})]})

    facts = {"customer": "Kapoor traders", "amount": 3000.0, "was_due_on": "2026-09-26", "days_overdue": 6}
    ok, src = drafts.write_message("payment_reminder", facts, Fake("Namaste Kapoor ji, Rs 3,000 baaki hain."), "m")
    assert src == "nemotron"
    for bad in ("Namaste, Rs 30,000 baaki hain.", "Namaste [Name], Rs 3,000 baaki hain."):
        text, src = drafts.write_message("payment_reminder", facts, Fake(bad), "m")
        assert src == "template" and "3,000" in text


def test_briefing_runs():
    c = fresh()
    text = db.format_briefing(db.briefing(c, TODAY))
    assert "Kapoor traders" in text and "DAILY BRIEFING" in text


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  ", t.__name__)
    print(f"\n{len(tests)} tests passed")
