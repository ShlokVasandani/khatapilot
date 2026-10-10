"""
SQLite storage, validation and simple business rules for the back-office agent.

The LLM extracts; this module decides what is safe to write. Anything that
fails validation, or needs the owner's judgement, goes to the review queue
instead of silently changing the books.
"""

import json
import sqlite3
from datetime import date, timedelta

VALID_INTENTS = {"order", "payment_promise", "payment_received", "payment_made",
                 "complaint", "inquiry", "other"}
VALID_DIRECTIONS = {"customer_owes_us", "we_owe_supplier"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS parties (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  name_key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'customer' CHECK (kind IN ('customer', 'supplier')),
  phone TEXT
);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  unit TEXT,
  stock_qty REAL NOT NULL DEFAULT 0,      -- available stock after pending orders
  reorder_level REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  raw_message TEXT,
  intent TEXT NOT NULL,
  party_id INTEGER REFERENCES parties(id),
  amount REAL,
  due_date TEXT,
  status TEXT NOT NULL DEFAULT 'recorded'
);
CREATE TABLE IF NOT EXISTS transaction_items (
  txn_id INTEGER NOT NULL REFERENCES transactions(id),
  item_id INTEGER NOT NULL REFERENCES items(id),
  quantity REAL,
  unit TEXT
);
CREATE TABLE IF NOT EXISTS dues (
  id INTEGER PRIMARY KEY,
  party_id INTEGER NOT NULL REFERENCES parties(id),
  direction TEXT NOT NULL CHECK (direction IN ('customer_owes_us', 'we_owe_supplier')),
  amount REAL NOT NULL,
  paid REAL NOT NULL DEFAULT 0,
  due_date TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  source_txn INTEGER REFERENCES transactions(id),
  bill_date TEXT
);
CREATE TABLE IF NOT EXISTS review_queue (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  raw_message TEXT,
  extraction TEXT,
  reason TEXT,
  resolved INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS day_closes (
  day TEXT PRIMARY KEY,
  closed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS snapshots (       -- what each customer owed when the day was closed
  day TEXT NOT NULL,
  party_id INTEGER NOT NULL REFERENCES parties(id),
  total REAL NOT NULL,
  lines TEXT NOT NULL,                       -- JSON: [{"date": "2026-09-28", "amount": 7000}, ...]
  PRIMARY KEY (day, party_id)
);
CREATE TABLE IF NOT EXISTS reminders_opened ( -- WhatsApp opened for this customer on this day
  day TEXT NOT NULL,
  party_id INTEGER NOT NULL REFERENCES parties(id),
  PRIMARY KEY (day, party_id)
);
"""


def connect(path: str = "shop.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn) -> None:
    """Add columns that older shop.db files don't have yet."""
    def cols(table):
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if "phone" not in cols("parties"):
        conn.execute("ALTER TABLE parties ADD COLUMN phone TEXT")
    if "bill_date" not in cols("dues"):
        conn.execute("ALTER TABLE dues ADD COLUMN bill_date TEXT")
    conn.commit()


def _key(name: str) -> str:
    return " ".join(name.lower().split())


def get_or_create_party(conn, name: str, kind: str = "customer") -> int:
    k = _key(name)
    row = conn.execute("SELECT id FROM parties WHERE name_key = ?", (k,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO parties (name, name_key, kind) VALUES (?, ?, ?)", (name.strip(), k, kind)
    )
    return cur.lastrowid


def get_or_create_item(conn, name: str, unit: str | None = None) -> int:
    k = _key(name)
    row = conn.execute("SELECT id, unit FROM items WHERE name = ?", (k,)).fetchone()
    if row:
        if unit and not row["unit"]:
            conn.execute("UPDATE items SET unit = ? WHERE id = ?", (unit, row["id"]))
        return row["id"]
    cur = conn.execute("INSERT INTO items (name, unit) VALUES (?, ?)", (k, unit))
    return cur.lastrowid


# ---------------------------------------------------------------- validation

def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(ex) -> list[str]:
    """Return a list of problems with an extraction; empty means it is safe to use."""
    if not isinstance(ex, dict):
        return ["extraction is not an object"]
    errors = []
    if ex.get("intent") not in VALID_INTENTS:
        errors.append(f"invalid intent: {ex.get('intent')!r}")
    amount = ex.get("amount_inr")
    if amount is not None and (not _is_num(amount) or amount < 0):
        errors.append(f"bad amount: {amount!r}")
    items = ex.get("items") or []
    if not isinstance(items, list):
        errors.append("items is not a list")
        items = []
    for it in items:
        if not isinstance(it, dict) or not str(it.get("name") or "").strip():
            errors.append("item without a name")
            continue
        q = it.get("quantity")
        if q is not None and (not _is_num(q) or q <= 0):
            errors.append(f"bad quantity for {it['name']}: {q!r}")
    due = ex.get("due_date")
    if due is not None:
        try:
            date.fromisoformat(due)
        except (TypeError, ValueError):
            errors.append(f"bad due_date: {due!r}")
    return errors


# ------------------------------------------------------------ applying data

def recent_duplicate(conn, raw: str, minutes: int = 10) -> bool:
    """True if this exact message (ignoring case and spacing) was already recorded a moment ago.
    Stops a double paste or double click from applying the same payment or order twice."""
    key = " ".join(raw.lower().split())
    for r in conn.execute(
            "SELECT raw_message FROM transactions WHERE status != 'logged' "
            "AND created_at >= datetime('now', ?)", (f"-{int(minutes)} minutes",)):
        if " ".join((r["raw_message"] or "").lower().split()) == key:
            return True
    return False


def _to_review(conn, raw, ex, reason) -> dict:
    with conn:
        conn.execute(
            "INSERT INTO review_queue (raw_message, extraction, reason) VALUES (?, ?, ?)",
            (raw, json.dumps(ex, ensure_ascii=False, default=str), reason),
        )
    return {"status": "review", "detail": reason}


def _insert_txn(conn, raw, intent, party_id, amount, due, status) -> int:
    cur = conn.execute(
        "INSERT INTO transactions (raw_message, intent, party_id, amount, due_date, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (raw, intent, party_id, amount, due, status),
    )
    return cur.lastrowid


def _clean_direction(value) -> str | None:
    """Direction is only a hint (a known party's kind decides), so forgive model typos."""
    v = str(value or "").lower()
    if "supplier" in v:
        return "we_owe_supplier"
    if "owes_us" in v or "ows_us" in v or "customer" in v:
        return "customer_owes_us"
    return None


def _resolve_direction(conn, party_name, explicit, intent) -> str:
    """Which way does the money flow? A known party's kind beats whatever the model guessed."""
    if party_name:
        row = conn.execute(
            "SELECT kind FROM parties WHERE name_key = ?", (_key(party_name),)
        ).fetchone()
        if row:
            return "we_owe_supplier" if row["kind"] == "supplier" else "customer_owes_us"
    if intent == "payment_made":
        return "we_owe_supplier"
    return _clean_direction(explicit) or "customer_owes_us"


def apply_extraction(conn, raw: str, ex: dict) -> dict:
    """Validate one extraction and update the books. Returns {status, detail}."""
    errors = validate(ex)
    if errors:
        return _to_review(conn, raw, ex, "; ".join(errors))

    intent = ex["intent"]
    amount = ex.get("amount_inr")
    due = ex.get("due_date")
    party_name = (ex.get("party") or "").strip() or None
    direction = _resolve_direction(conn, party_name, ex.get("direction"), intent)
    kind = "supplier" if direction == "we_owe_supplier" else "customer"
    items = ex.get("items") or []

    if intent == "complaint":
        return _to_review(conn, raw, ex, "complaint: needs the owner's attention")
    if intent == "other":
        return _to_review(conn, raw, ex, "could not classify this message")

    if intent == "inquiry":
        with conn:
            party_id = get_or_create_party(conn, party_name, kind) if party_name else None
            _insert_txn(conn, raw, intent, party_id, None, None, "logged")
        return {"status": "recorded", "detail": "inquiry logged"}

    if intent == "order":
        if not items:
            return _to_review(conn, raw, ex, "order without any items")
        shortages = []
        with conn:
            party_id = get_or_create_party(conn, party_name, kind) if party_name else None
            txn = _insert_txn(conn, raw, intent, party_id, amount, due, "pending")
            for it in items:
                item_id = get_or_create_item(conn, it["name"], it.get("unit"))
                qty = it.get("quantity")
                conn.execute(
                    "INSERT INTO transaction_items (txn_id, item_id, quantity, unit) VALUES (?, ?, ?, ?)",
                    (txn, item_id, qty, it.get("unit")),
                )
                if qty:
                    conn.execute(
                        "UPDATE items SET stock_qty = stock_qty - ? WHERE id = ?", (qty, item_id)
                    )
                    left = conn.execute(
                        "SELECT stock_qty FROM items WHERE id = ?", (item_id,)
                    ).fetchone()["stock_qty"]
                    if left < 0:
                        shortages.append(f"{it['name']} short by {-left:g}")
        detail = f"order for {party_name or 'unnamed customer'}, {len(items)} item(s)"
        if shortages:
            detail += " | STOCK SHORT: " + ", ".join(shortages)
        return {"status": "recorded", "detail": detail}

    if intent == "payment_promise":
        if not party_name or amount is None or amount <= 0:
            return _to_review(conn, raw, ex, "payment promise needs a party and an amount")
        with conn:
            party_id = get_or_create_party(conn, party_name, kind)
            txn = _insert_txn(conn, raw, intent, party_id, amount, due, "recorded")
            existing = conn.execute(
                "SELECT id FROM dues WHERE party_id = ? AND direction = ? AND status = 'open' "
                "AND ABS((amount - paid) - ?) < 0.01",
                (party_id, direction, amount),
            ).fetchone()
            if existing:  # same debt, new promised date: update, don't duplicate
                conn.execute("UPDATE dues SET due_date = ? WHERE id = ?", (due, existing["id"]))
                detail = f"{party_name}: promised date for existing {amount:g} due set to {due}"
            else:
                conn.execute(
                    "INSERT INTO dues (party_id, direction, amount, due_date, source_txn, bill_date) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (party_id, direction, amount, due, txn, date.today().isoformat()),
                )
                detail = f"new due: {party_name} {amount:g} ({direction}), due {due or 'no date'}"
        return {"status": "recorded", "detail": detail}

    if intent in ("payment_received", "payment_made"):
        if amount is None or amount <= 0:
            return _to_review(conn, raw, ex, "payment without a valid amount")
        if not party_name:
            return _to_review(conn, raw, ex, "payment received but payer is not identified")
        with conn:
            party_id = get_or_create_party(conn, party_name, kind)
            txn = _insert_txn(conn, raw, intent, party_id, amount, None, "recorded")
            remaining = amount
            open_dues = conn.execute(
                "SELECT id, amount, paid FROM dues WHERE party_id = ? AND direction = ? "
                "AND status = 'open' ORDER BY due_date IS NULL, due_date, id",
                (party_id, direction),
            ).fetchall()
            for d in open_dues:
                if remaining <= 0:
                    break
                pay = min(d["amount"] - d["paid"], remaining)
                new_paid = d["paid"] + pay
                status = "paid" if new_paid >= d["amount"] - 0.01 else "open"
                conn.execute(
                    "UPDATE dues SET paid = ?, status = ? WHERE id = ?", (new_paid, status, d["id"])
                )
                remaining -= pay
            if remaining > 0:
                conn.execute("UPDATE transactions SET status = 'unallocated' WHERE id = ?", (txn,))
        applied = amount - max(remaining, 0)
        detail = f"{party_name}: {applied:g} applied to dues"
        if remaining > 0:
            detail += f", {remaining:g} unallocated (no matching open due)"
        return {"status": "recorded", "detail": detail}

    return _to_review(conn, raw, ex, f"unhandled intent {intent!r}")


def receive_stock(conn, name: str, qty: float, unit: str | None = None) -> None:
    """Add stock from a supplier invoice or delivery."""
    with conn:
        item_id = get_or_create_item(conn, name, unit)
        conn.execute("UPDATE items SET stock_qty = stock_qty + ? WHERE id = ?", (qty, item_id))


# ------------------------------------------------------------------ queries

def overdue_dues(conn, today: date | None = None):
    today = (today or date.today()).isoformat()
    return conn.execute(
        "SELECT p.name AS party, d.direction, d.amount - d.paid AS remaining, d.due_date "
        "FROM dues d JOIN parties p ON p.id = d.party_id "
        "WHERE d.status = 'open' AND d.due_date IS NOT NULL AND d.due_date < ? "
        "ORDER BY d.due_date",
        (today,),
    ).fetchall()


def dues_due_soon(conn, days: int = 3, today: date | None = None):
    today = today or date.today()
    return conn.execute(
        "SELECT p.name AS party, d.direction, d.amount - d.paid AS remaining, d.due_date "
        "FROM dues d JOIN parties p ON p.id = d.party_id "
        "WHERE d.status = 'open' AND d.due_date BETWEEN ? AND ? ORDER BY d.due_date",
        (today.isoformat(), (today + timedelta(days=days)).isoformat()),
    ).fetchall()


def low_stock(conn):
    return conn.execute(
        "SELECT name, unit, stock_qty, reorder_level FROM items "
        "WHERE stock_qty <= reorder_level ORDER BY stock_qty - reorder_level"
    ).fetchall()


def open_totals(conn) -> dict:
    rows = conn.execute(
        "SELECT direction, COALESCE(SUM(amount - paid), 0) AS total FROM dues "
        "WHERE status = 'open' GROUP BY direction"
    ).fetchall()
    totals = {"customer_owes_us": 0.0, "we_owe_supplier": 0.0}
    totals.update({r["direction"]: r["total"] for r in rows})
    return totals


def pending_review(conn):
    return conn.execute(
        "SELECT id, raw_message, reason FROM review_queue WHERE resolved = 0 ORDER BY id"
    ).fetchall()


def briefing(conn, today: date | None = None) -> dict:
    """Structured facts for the daily briefing. The LLM writes the prose from this."""
    return {
        "date": (today or date.today()).isoformat(),
        "overdue": [dict(r) for r in overdue_dues(conn, today)],
        "due_soon": [dict(r) for r in dues_due_soon(conn, 3, today)],
        "low_stock": [dict(r) for r in low_stock(conn)],
        "totals": open_totals(conn),
        "needs_review": [dict(r) for r in pending_review(conn)],
    }


def format_briefing(b: dict) -> str:
    """Plain-text version, used until the LLM-written briefing is wired in."""
    lines = [f"DAILY BRIEFING - {b['date']}", ""]
    t = b["totals"]
    lines.append(
        f"To collect: Rs {t['customer_owes_us']:,.0f}   To pay suppliers: Rs {t['we_owe_supplier']:,.0f}"
    )
    lines.append("\nOverdue:")
    lines += [
        f"  - {r['party']}: Rs {r['remaining']:,.0f} ({r['direction']}), was due {r['due_date']}"
        for r in b["overdue"]
    ] or ["  none"]
    lines.append("\nDue in the next 3 days:")
    lines += [
        f"  - {r['party']}: Rs {r['remaining']:,.0f} ({r['direction']}) on {r['due_date']}"
        for r in b["due_soon"]
    ] or ["  none"]
    lines.append("\nReorder / low stock:")
    lines += [
        f"  - {r['name']}: {r['stock_qty']:g} {r['unit'] or ''} left (reorder at {r['reorder_level']:g})"
        for r in b["low_stock"]
    ] or ["  none"]
    lines.append("\nNeeds your review:")
    lines += [f"  - \"{r['raw_message']}\" -> {r['reason']}" for r in b["needs_review"]] or ["  none"]
    return "\n".join(lines)


# --------------------------------------------------------------------- demo

def seed_demo(conn, today: date | None = None) -> None:
    """Starting state for the demo: some stock, some customers with old dues."""
    today = today or date.today()
    stock = [  # name, unit, stock, reorder level
        ("sugar", "kg", 60, 40), ("parle-g", "packet", 80, 30), ("tel", "dabba", 25, 10),
        ("atta", "bori", 12, 5), ("chawal", "kg", 80, 25), ("dal", "kg", 45, 20),
        ("basmati", "kg", 50, 20), ("chai patti", "kg", 8, 5), ("namak", "kg", 20, 10),
        ("maida", "kg", 25, 10),
    ]
    with conn:
        for name, unit, qty, level in stock:
            conn.execute(
                "INSERT OR IGNORE INTO items (name, unit, stock_qty, reorder_level) VALUES (?, ?, ?, ?)",
                (name, unit, qty, level),
            )
        for name, kind in [("Sharma ji", "customer"), ("Gupta store", "customer"),
                           ("Ramesh bhai", "customer"), ("Kapoor traders", "customer"),
                           ("Verma ji", "customer"), ("Mehta wholesale", "supplier")]:
            get_or_create_party(conn, name, kind)
        existing = conn.execute("SELECT COUNT(*) AS n FROM dues").fetchone()["n"]
        if existing == 0:
            for name, direction, amount, bill_days_ago, due_days_ago in [
                ("Kapoor traders", "customer_owes_us", 7000, 9, 6),
                ("Kapoor traders", "customer_owes_us", 5000, 7, 4),
                ("Sharma ji", "customer_owes_us", 4500, 5, 2),
                ("Mehta wholesale", "we_owe_supplier", 8000, 4, -3),
            ]:
                pid = get_or_create_party(conn, name)
                conn.execute(
                    "INSERT INTO dues (party_id, direction, amount, due_date, bill_date) VALUES (?, ?, ?, ?, ?)",
                    (pid, direction, amount, (today - timedelta(days=due_days_ago)).isoformat(),
                     (today - timedelta(days=bill_days_ago)).isoformat()),
                )
        # obviously fake numbers so the WhatsApp links work in the demo; edit them in the dashboard
        for n, (name, phone) in enumerate([("Kapoor traders", "919000000001"), ("Sharma ji", "919000000002"),
                                           ("Gupta store", "919000000003"), ("Ramesh bhai", "919000000004"),
                                           ("Verma ji", "919000000005")]):
            conn.execute("UPDATE parties SET phone = ? WHERE name_key = ? AND phone IS NULL", (phone, _key(name)))
