"""
End-of-day close and the collections list.

At close, every customer's balance is frozen. Next morning's reminder messages use those frozen
figures, so the amount and bill lines don't shift during the day. The close also writes two
spreadsheets (open them in Excel) for the accountant:

    eod/daybook_YYYY-MM-DD.csv       every transaction of the day
    eod/outstanding_YYYY-MM-DD.csv   who owes what, bill by bill, both sides

Usage:
    python eod.py            # close today
    python eod.py 2026-10-02 # close a given day
"""

import csv
import json
import os
import re
import sys
import urllib.parse
from datetime import date

import db

SHOP_NAME = os.environ.get("SHOP_NAME", "Shree Fruits")
OPEN = 0.5  # balances under half a rupee count as settled


# ---------------------------------------------------------------- formatting

def inr(n: float) -> str:
    """Rs 7,000 / Rs 1,20,000 (Indian digit grouping)."""
    n = int(round(n))
    s = str(abs(n))
    if len(s) > 3:
        head, tail, parts = s[:-3], s[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + "Rs " + s


def short_date(iso: str | None) -> str | None:
    if not iso:
        return None
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')}"


def reminder_text(party: str, lines: list[dict], firm: str | None = None) -> str:
    """The message the owner sends: one line per unpaid bill, then the total."""
    firm = firm or SHOP_NAME
    rows = []
    for ln in lines:
        d = short_date(ln.get("date"))
        rows.append(f"{firm} - {inr(ln['amount'])}" + (f" - {d}" if d else ""))
    total = sum(ln["amount"] for ln in lines)
    return (f"Namaste {party},\nAapke baaki payments:\n\n" + "\n".join(rows) +
            f"\n\nTotal: {inr(total)}\n\nJald se jald hisaab clear kare.\nThank you")


def normalize_phone(raw: str) -> str:
    """Digits with country code, as wa.me wants. 10-digit Indian numbers get 91 added."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10:
        digits = "91" + digits
    if not 11 <= len(digits) <= 15:
        raise ValueError("Enter a phone number with 10 digits (or with country code)")
    return digits


def wa_link(phone: str | None, text: str) -> str:
    base = f"https://wa.me/{phone}" if phone else "https://wa.me/"
    return base + "?text=" + urllib.parse.quote(text)


def set_phone(conn, party_id: int, raw: str) -> str:
    phone = normalize_phone(raw)
    with conn:
        conn.execute("UPDATE parties SET phone = ? WHERE id = ?", (phone, party_id))
    return phone


# --------------------------------------------------------------------- bills

def live_bills(conn, party_id: int) -> list[dict]:
    """Unpaid customer bills right now, oldest first."""
    rows = conn.execute(
        "SELECT COALESCE(bill_date, due_date) AS d, amount - paid AS remaining FROM dues "
        "WHERE party_id = ? AND direction = 'customer_owes_us' AND status = 'open' "
        "AND amount - paid > ? ORDER BY d IS NULL, d, id", (party_id, OPEN)).fetchall()
    return [{"date": r["d"], "amount": r["remaining"]} for r in rows]


def close_day(conn, day: date | None = None, out_dir: str = "eod") -> dict:
    """Freeze every customer's balance and write the day's spreadsheets."""
    day = day or date.today()
    key = day.isoformat()
    parties = conn.execute(
        "SELECT DISTINCT p.id FROM parties p JOIN dues d ON d.party_id = p.id "
        "WHERE d.direction = 'customer_owes_us' AND d.status = 'open'").fetchall()
    frozen = 0.0
    with conn:
        conn.execute("DELETE FROM snapshots WHERE day = ?", (key,))
        for p in parties:
            lines = live_bills(conn, p["id"])
            if not lines:
                continue
            total = sum(ln["amount"] for ln in lines)
            frozen += total
            conn.execute("INSERT INTO snapshots (day, party_id, total, lines) VALUES (?, ?, ?, ?)",
                         (key, p["id"], total, json.dumps(lines)))
        conn.execute("INSERT OR REPLACE INTO day_closes (day, closed_at) VALUES (?, datetime('now'))", (key,))
    files = write_sheets(conn, day, out_dir)
    return {"day": key, "frozen_total": frozen, "files": files}


def write_sheets(conn, day: date, out_dir: str = "eod") -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    key = day.isoformat()

    book = os.path.join(out_dir, f"daybook_{key}.csv")
    with open(book, "w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel shows Hinglish properly
        w = csv.writer(f)
        w.writerow(["Time", "Party", "Type", "Items", "Amount (Rs)", "Status", "Message"])
        for t in conn.execute(
            "SELECT t.id, strftime('%H:%M', t.created_at, 'localtime') AS time, p.name AS party, "
            "t.intent, t.amount, t.status, t.raw_message FROM transactions t "
            "LEFT JOIN parties p ON p.id = t.party_id "
            "WHERE date(t.created_at, 'localtime') = ? ORDER BY t.id", (key,)).fetchall():
            items = "; ".join(
                f"{r['quantity']:g} {r['unit'] or ''} {r['name']}".replace("  ", " ")
                if r["quantity"] is not None else r["name"]
                for r in conn.execute(
                    "SELECT ti.quantity, ti.unit, i.name FROM transaction_items ti "
                    "JOIN items i ON i.id = ti.item_id WHERE ti.txn_id = ?", (t["id"],)))
            w.writerow([t["time"], t["party"] or "", t["intent"], items,
                        "" if t["amount"] is None else f"{t['amount']:g}", t["status"], t["raw_message"] or ""])

    out = os.path.join(out_dir, f"outstanding_{key}.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Side", "Party", "Phone", "Bill date", "Due date", "Amount (Rs)", "Paid (Rs)",
                    "Remaining (Rs)", "Days overdue"])
        totals = {"customer_owes_us": 0.0, "we_owe_supplier": 0.0}
        for r in conn.execute(
            "SELECT d.direction, p.name, p.phone, d.bill_date, d.due_date, d.amount, d.paid "
            "FROM dues d JOIN parties p ON p.id = d.party_id WHERE d.status = 'open' "
            "ORDER BY d.direction DESC, p.name, d.bill_date, d.id").fetchall():
            left = r["amount"] - r["paid"]
            totals[r["direction"]] += left
            late = ""
            if r["due_date"] and r["due_date"] < key:
                late = (day - date.fromisoformat(r["due_date"])).days
            w.writerow(["To collect" if r["direction"] == "customer_owes_us" else "To pay",
                        r["name"], r["phone"] or "", r["bill_date"] or "", r["due_date"] or "",
                        f"{r['amount']:g}", f"{r['paid']:g}", f"{left:g}", late])
        w.writerow([])
        w.writerow(["TOTAL to collect", "", "", "", "", "", "", f"{totals['customer_owes_us']:g}", ""])
        w.writerow(["TOTAL to pay", "", "", "", "", "", "", f"{totals['we_owe_supplier']:g}", ""])
    return [book, out]


def last_close(conn) -> str | None:
    r = conn.execute("SELECT day FROM day_closes ORDER BY day DESC LIMIT 1").fetchone()
    return r["day"] if r else None


def is_closed(conn, day: date) -> bool:
    return bool(conn.execute("SELECT 1 FROM day_closes WHERE day = ?", (day.isoformat(),)).fetchone())


# --------------------------------------------------------------- collections

def mark_opened(conn, party_id: int, day: date | None = None) -> None:
    with conn:
        conn.execute("INSERT OR IGNORE INTO reminders_opened (day, party_id) VALUES (?, ?)",
                     ((day or date.today()).isoformat(), party_id))


def collections(conn, today: date | None = None) -> list[dict]:
    """Customers who owe money, with the message to send. Uses the last close's figures."""
    today = today or date.today()
    out = []
    for p in conn.execute(
        "SELECT DISTINCT p.id, p.name, p.phone FROM parties p JOIN dues d ON d.party_id = p.id "
        "WHERE d.direction = 'customer_owes_us' AND d.status = 'open'").fetchall():
        live = live_bills(conn, p["id"])
        live_total = sum(ln["amount"] for ln in live)
        if live_total <= OPEN:
            continue
        snap = conn.execute("SELECT day, total, lines FROM snapshots WHERE party_id = ? "
                            "ORDER BY day DESC LIMIT 1", (p["id"],)).fetchone()
        if snap:
            lines, frozen_total, frozen_day = json.loads(snap["lines"]), snap["total"], snap["day"]
            state = "changed" if abs(frozen_total - live_total) > OPEN else "frozen"
        else:
            lines, frozen_total, frozen_day, state = live, None, None, "new"
        oldest = conn.execute(
            "SELECT MIN(due_date) AS d FROM dues WHERE party_id = ? AND direction = 'customer_owes_us' "
            "AND status = 'open' AND amount - paid > ? AND due_date IS NOT NULL", (p["id"], OPEN)).fetchone()["d"]
        text = reminder_text(p["name"], lines)
        out.append({
            "party_id": p["id"], "name": p["name"], "phone": p["phone"],
            "live_total": live_total, "frozen_total": frozen_total, "frozen_day": frozen_day,
            "state": state,  # frozen: safe to send | changed: balance moved since close | new: never closed
            "days_overdue": (today - date.fromisoformat(oldest)).days if oldest and oldest < today.isoformat() else 0,
            "text": text, "link": wa_link(p["phone"], text),
            "opened_today": bool(conn.execute(
                "SELECT 1 FROM reminders_opened WHERE day = ? AND party_id = ?",
                (today.isoformat(), p["id"])).fetchone()),
        })
    out.sort(key=lambda c: (-c["days_overdue"], -c["live_total"]))
    return out


if __name__ == "__main__":
    day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    result = close_day(db.connect("shop.db"), day)
    print(f"Closed {result['day']}. Customers owe {inr(result['frozen_total'])} in total.")
    for f in result["files"]:
        print("  wrote", f)
