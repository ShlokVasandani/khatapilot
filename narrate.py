"""
Turn the ledger's briefing facts into a short morning message for the owner,
written by Nemotron on Nebius Token Factory.

The model only writes prose. Every number it uses is checked against the facts;
if it invents or changes a figure we fall back to the plain-text briefing.

Usage:
    python narrate.py                 # briefing for the current shop.db (English)
    python narrate.py --lang hinglish
"""

import argparse
import json
import os
import re

import db

TOTAL_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

PROMPT = """You are the back-office assistant of a small Indian shop. Write the owner's \
morning briefing from the FACTS below.

Style: <<LANG>>. Short and warm, like a trusted munim ji talking. Start with "Namaste" (never \
"sir" or "boss"). Plain text only, no markdown, no tables. Use at most 120 words.
<<EXAMPLE>>

Order: (1) money to collect, with the overdue ones named first; (2) money to pay suppliers and \
when; (3) stock to reorder; (4) how many messages need the owner's decision. End with one line \
saying what you suggest doing first.

Hard rules:
- Use ONLY numbers, names and dates that appear in the FACTS. Never calculate new totals, never round.
- Write rupee amounts in full as Rs 14,000, not 14k.
- "reorder_at" is the stock level at which the shop reorders. Say "only 10 kg left", never "restock at 40 kg".
- Do not mention anything that is not in the FACTS.

FACTS:
<<FACTS>>
"""

HINGLISH_EXAMPLE = (
    'For Hinglish, write mostly Hindi words in Roman script (vasool, dene hain, bacha hai, sabse pehle), '
    'not English sentences. Example: "Namaste! Aaj Rs 14,000 vasool karna hai. Sabse pehle Kapoor traders '
    'ka Rs 3,000, jo 2026-09-26 se pending hai. Mehta wholesale ko Rs 5,000 dene hain. Sugar sirf 10 kg '
    'bacha hai, order kar dein. 4 messages aapke decision ka wait kar rahe hain."'
)

LANGS = {
    "english": "simple English",
    "hinglish": "Hinglish (Hindi in Roman script mixed with simple English, the way shopkeepers text)",
}


def _numbers(text: str) -> set[float]:
    out = set()
    for tok in TOTAL_RE.findall(text):
        try:
            out.add(float(tok.replace(",", "")))
        except ValueError:
            pass
    return out


def numbers_ok(text: str, facts: dict) -> list[float]:
    """Return numbers in `text` that are not in `facts` (small numbers, 31 or less, are allowed:
    dates and day counts)."""
    allowed = _numbers(json.dumps(facts, ensure_ascii=False, default=str))
    return sorted(n for n in _numbers(text) if n > 31 and n not in allowed)


def _facts_for_model(b: dict) -> dict:
    """Trim the briefing to what the model needs, with plain-language field names."""
    t = b["totals"]
    return {
        "today": b["date"],
        "total_to_collect": t["customer_owes_us"],
        "total_to_pay_suppliers": t["we_owe_supplier"],
        "overdue": [
            {"party": r["party"], "amount": r["remaining"], "was_due": r["due_date"],
             "side": "customer owes us" if r["direction"] == "customer_owes_us" else "we owe supplier"}
            for r in b["overdue"]
        ],
        "due_in_next_3_days": [
            {"party": r["party"], "amount": r["remaining"], "due": r["due_date"],
             "side": "customer owes us" if r["direction"] == "customer_owes_us" else "we owe supplier"}
            for r in b["due_soon"]
        ],
        "low_stock": [
            {"item": r["name"], "left": r["stock_qty"], "unit": r["unit"], "reorder_at": r["reorder_level"]}
            for r in b["low_stock"]
        ],
        "messages_needing_owner_decision": len(b["needs_review"]),
    }


def narrate(b: dict, lang: str = "english", client=None, model: str | None = None) -> tuple[str, str]:
    """Return (text, source) where source is 'nemotron' or 'fallback'."""
    facts = _facts_for_model(b)
    try:
        if client is None:
            from extract import TEXT_MODEL, client as _client
            client, model = _client, model or os.environ.get("BRIEFING_MODEL") or TEXT_MODEL
        prompt = (PROMPT.replace("<<LANG>>", LANGS.get(lang, LANGS["english"]))
                  .replace("<<EXAMPLE>>", HINGLISH_EXAMPLE if lang == "hinglish" else "")
                  .replace("<<FACTS>>", json.dumps(facts, ensure_ascii=False, indent=1)))
        for _ in range(2):
            resp = client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}], temperature=0.3)
            text = re.sub(r"<think>.*?</think>", "", resp.choices[0].message.content or "",
                          flags=re.DOTALL).strip()
            if text and not numbers_ok(text, facts):
                return text, "nemotron"
    except Exception:
        pass
    return db.format_briefing(b), "fallback"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=list(LANGS), default="english")
    ap.add_argument("--db", default="shop.db")
    args = ap.parse_args()
    conn = db.connect(args.db)
    text, source = narrate(db.briefing(conn), args.lang)
    print(f"[{source}]\n\n{text}")
