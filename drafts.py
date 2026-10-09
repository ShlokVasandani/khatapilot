"""
Draft WhatsApp reorder messages to suppliers for the owner to approve.

Nemotron writes the wording; amounts, dates and quantities come from the ledger.
Nothing is ever sent automatically: every draft waits as 'pending' until the owner
approves, edits or rejects it.

Usage:
    python drafts.py generate        # draft supplier reorder messages from the current shop.db
    python drafts.py list
    python drafts.py review          # approve / edit / reject one by one
    python drafts.py approve 3
    python drafts.py reject 3
    python drafts.py edit 3 "new text"
"""

import json
import math
import os
import re
import sys
import urllib.parse
from datetime import date

import db
from narrate import numbers_ok

DRAFT_SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  kind TEXT NOT NULL,                -- reorder
  party TEXT NOT NULL,
  dedupe_key TEXT NOT NULL,
  facts TEXT NOT NULL,
  body TEXT NOT NULL,
  source TEXT NOT NULL,              -- nemotron | template | owner
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected'))
);
"""

PROMPT = """Write ONE WhatsApp message from a small Indian shop owner. Language: Hinglish (Hindi in \
Roman script with simple English words), the way shopkeepers text. <<GOAL>>

Rules:
- At most 45 words. Polite and respectful, never threatening or rude.
- Use the exact amounts, dates, names and quantities from FACTS. Do not invent or change any number.
- Write rupees as Rs 3,000.
- Write mostly in Hindi words in Roman script (aapka, kripya, kab tak, baaki, dhanyavaad). Do not write full English sentences.
- No placeholders such as [Name], no emojis, no markdown.
- Output only the message text.

Example of the tone:
"Namaste Mehta ji, hamein sugar 70 kg aur dal 25 kg chahiye. Kab tak bhej sakenge? Dhanyavaad."

FACTS:
<<FACTS>>
"""

GOALS = {
    "reorder": "Goal: order these items from the supplier and ask when they can deliver.",
}


def ensure(conn) -> None:
    conn.executescript(DRAFT_SCHEMA)


def _suggest_qty(stock: float, level: float) -> int:
    """Top up to twice the reorder level (at least 1)."""
    return max(1, math.ceil(level * 2 - stock))


def plan(conn, today: date | None = None) -> list[dict]:
    """What the shop needs to order from suppliers, as facts only (no wording yet).
    Customer payment reminders are built in eod.py from the end-of-day figures."""
    out = []
    low = db.low_stock(conn)
    supplier = conn.execute(
        "SELECT name FROM parties WHERE kind='supplier' ORDER BY id LIMIT 1").fetchone()
    if low and supplier:
        items = [{"item": r["name"], "unit": r["unit"],
                  "order_qty": _suggest_qty(r["stock_qty"], r["reorder_level"])} for r in low]
        sig = ",".join(f"{i['item']}:{i['order_qty']}" for i in items)
        out.append({"kind": "reorder", "party": supplier["name"],
                    "facts": {"supplier": supplier["name"], "items": items},
                    "key": f"reorder|{supplier['name']}|{sig}"})
    return out


def template(kind: str, facts: dict) -> str:
    """Plain fallback wording, used when the model is unavailable or fails the number check."""
    lines = "\n".join(f"- {i['item']}: {i['order_qty']:g} {i['unit'] or ''}".rstrip() for i in facts["items"])
    return (f"Namaste {facts['supplier']}, hamein ye maal chahiye:\n{lines}\n"
            f"Kab tak bhej sakte hain? Dhanyavaad.")


def write_message(kind: str, facts: dict, client=None, model: str | None = None) -> tuple[str, str]:
    """Return (text, source). Falls back to the template on any problem."""
    try:
        if client is None:
            from extract import TEXT_MODEL, client as _client
            client, model = _client, model or os.environ.get("BRIEFING_MODEL") or TEXT_MODEL
        prompt = (PROMPT.replace("<<GOAL>>", GOALS[kind])
                  .replace("<<FACTS>>", json.dumps(facts, ensure_ascii=False, indent=1)))
        for _ in range(2):
            resp = client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}], temperature=0.4)
            text = re.sub(r"<think>.*?</think>", "", resp.choices[0].message.content or "",
                          flags=re.DOTALL).strip().strip('"')
            if text and "[" not in text and not numbers_ok(text, facts):
                return text, "nemotron"
    except Exception:
        pass
    return template(kind, facts), "template"


def generate(conn, today: date | None = None, client=None, model=None, use_llm: bool = True) -> list[int]:
    """Create pending drafts for anything not already drafted. Returns the new draft ids."""
    ensure(conn)
    new_ids = []
    todo = [p for p in plan(conn, today)
            if not conn.execute("SELECT 1 FROM drafts WHERE dedupe_key=? AND status IN ('pending','approved')",
                                (p["key"],)).fetchone()]
    if use_llm and todo:  # the model calls are slow, so write all messages in parallel
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            texts = list(pool.map(lambda p: write_message(p["kind"], p["facts"], client, model), todo))
    else:
        texts = [(template(p["kind"], p["facts"]), "template") for p in todo]
    for p, (body, source) in zip(todo, texts):
        cur = conn.execute(
            "INSERT INTO drafts (kind, party, dedupe_key, facts, body, source) VALUES (?,?,?,?,?,?)",
            (p["kind"], p["party"], p["key"], json.dumps(p["facts"]), body, source))
        new_ids.append(cur.lastrowid)
    conn.commit()
    return new_ids


def pending(conn):
    ensure(conn)
    return conn.execute("SELECT * FROM drafts WHERE status='pending' ORDER BY id").fetchall()


def set_status(conn, draft_id: int, status: str) -> None:
    ensure(conn)
    if not conn.execute("SELECT 1 FROM drafts WHERE id=?", (draft_id,)).fetchone():
        raise KeyError(f"no draft {draft_id}")
    conn.execute("UPDATE drafts SET status=? WHERE id=?", (status, draft_id))
    conn.commit()


def edit(conn, draft_id: int, text: str) -> None:
    ensure(conn)
    conn.execute("UPDATE drafts SET body=?, source='owner' WHERE id=?", (text.strip(), draft_id))
    conn.commit()


def whatsapp_link(body: str) -> str:
    return "https://wa.me/?text=" + urllib.parse.quote(body)


def _show(d) -> None:
    print(f"\n#{d['id']}  [{d['status']}]  {d['kind']}  ->  {d['party']}   (written by {d['source']})")
    print("-" * 60)
    print(d["body"])


def _review(conn) -> None:
    items = pending(conn)
    if not items:
        print("No drafts waiting.")
        return
    for d in items:
        _show(d)
        while True:
            c = input("\n[a]pprove  [e]dit  [r]eject  [s]kip  > ").strip().lower()
            if c == "a":
                set_status(conn, d["id"], "approved")
                print("Approved. Open this link to send it on WhatsApp:\n" + whatsapp_link(
                    conn.execute("SELECT body FROM drafts WHERE id=?", (d["id"],)).fetchone()["body"]))
                break
            if c == "e":
                edit(conn, d["id"], input("New text: "))
                _show(conn.execute("SELECT * FROM drafts WHERE id=?", (d["id"],)).fetchone())
                continue
            if c == "r":
                set_status(conn, d["id"], "rejected")
                break
            if c == "s":
                break


def main(argv: list[str]) -> None:
    if not argv:
        sys.exit(__doc__)
    conn = db.connect("shop.db")
    ensure(conn)
    cmd = argv[0]
    if cmd == "generate":
        ids = generate(conn)
        print(f"{len(ids)} new draft(s). Waiting for approval: {len(pending(conn))}")
        for d in pending(conn):
            _show(d)
    elif cmd == "list":
        rows = conn.execute("SELECT * FROM drafts ORDER BY id").fetchall()
        for d in rows:
            _show(d)
        if not rows:
            print("No drafts yet. Run: python drafts.py generate")
    elif cmd == "review":
        _review(conn)
    elif cmd in ("approve", "reject") and len(argv) == 2:
        set_status(conn, int(argv[1]), "approved" if cmd == "approve" else "rejected")
        print(f"Draft {argv[1]} {cmd}d.")
    elif cmd == "edit" and len(argv) == 3:
        edit(conn, int(argv[1]), argv[2])
        print(f"Draft {argv[1]} updated.")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
