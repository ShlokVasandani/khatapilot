"""
Accuracy check for the Nemotron extraction step, against hand-labelled messages (eval_set.json).

    python evalrun.py            # runs the model on every message, prints a report, saves eval_results.json

A message counts as correct only if intent, party, amount (when labelled), direction (when labelled)
and the item names + quantities (when labelled) all match. We also report how many wrong answers the
validation code stopped before they reached the ledger.
"""

import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import db

HERE = os.path.dirname(os.path.abspath(__file__))
SETS = [("demo", os.path.join(HERE, "eval_set.json")),          # the 28 demo messages (prompt was tuned on this kind)
        ("holdout", os.path.join(HERE, "eval_holdout.json"))]   # 20 messages written after the prompt was frozen
SET_PATH = SETS[0][1]
RESULT_PATH = os.path.join(HERE, "eval_results.json")


def _norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def _item_match(want, got_items) -> bool:
    name, qty = _norm(want[0]), want[1]
    for g in got_items or []:
        gname = _norm(g.get("name"))
        if (name in gname or gname in name) and gname and g.get("quantity") == qty:
            return True
    return False


def score(label: dict, got: dict) -> list[str]:
    """Return the list of fields that are wrong (empty list = correct)."""
    bad = []
    if got.get("intent") != label["intent"]:
        bad.append("intent")
    if "party" in label and _norm(got.get("party")) != _norm(label["party"]):
        bad.append("party")
    if "amount" in label and got.get("amount_inr") != label["amount"]:
        bad.append("amount")
    if "direction" in label and got.get("direction") != label["direction"]:
        bad.append("direction")
    if "items" in label and not all(_item_match(w, got.get("items")) for w in label["items"]):
        bad.append("items")
    return bad


def reaches_ledger(got: dict) -> bool:
    """Would this extraction be written to the books (true) or stopped for the owner (false)?"""
    return not db.validate(got) and got.get("intent") not in ("complaint", "other")


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    ok = sum(1 for r in rows if r["correct"])
    wrong = [r for r in rows if not r["correct"]]
    lat = [r["latency_ms"] for r in rows if r.get("latency_ms")]
    by_field: dict[str, int] = {}
    for r in wrong:
        for f in r["wrong_fields"]:
            by_field[f] = by_field.get(f, 0) + 1
    return {
        "total": n, "correct": ok, "accuracy": round(ok / n * 100, 1) if n else 0,
        "wrong": len(wrong),
        "guard_fixed": sum(1 for r in rows if r.get("guard_fixed")),
        "caught_before_ledger": sum(1 for r in wrong if not r["reached_ledger"]),
        "wrong_reached_ledger": sum(1 for r in wrong if r["reached_ledger"]),
        "wrong_by_field": by_field,
        "by_set": {name: {"total": sum(1 for r in rows if r.get("set") == name),
                          "correct": sum(1 for r in rows if r.get("set") == name and r["correct"])}
                   for name in dict.fromkeys(r.get("set") for r in rows if r.get("set"))},
        "avg_latency_ms": int(statistics.mean(lat)) if lat else 0,
        "p95_latency_ms": int(sorted(lat)[max(0, int(len(lat) * .95) - 1)]) if lat else 0,
        "prompt_tokens": sum(r.get("prompt_tokens", 0) for r in rows),
        "completion_tokens": sum(r.get("completion_tokens", 0) for r in rows),
    }


def load_labels() -> list[dict]:
    out = []
    for name, path in SETS:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                out += [dict(l, set=name) for l in json.load(f)]
    return out


def run(extract_fn, progress=None, workers: int = 4) -> dict:
    """extract_fn(message) -> (extraction_dict, meta_dict). Returns {summary, rows, at}."""
    labels = load_labels()

    def one(label):
        try:
            got, meta = extract_fn(label["m"])
            wrong = score(label, got)
            row = {"message": label["m"], "set": label["set"], "expected": {k: v for k, v in label.items() if k not in ("m", "set")}, "got": got,
                   "correct": not wrong, "wrong_fields": wrong, "reached_ledger": reaches_ledger(got), **meta}
        except Exception as e:
            row = {"message": label["m"], "set": label["set"], "expected": label, "got": {}, "correct": False,
                   "wrong_fields": ["error"], "reached_ledger": False, "error": str(e)}
        if progress:
            progress(row)
        return row

    with ThreadPoolExecutor(workers) as pool:
        rows = list(pool.map(one, labels))
    result = {"at": time.strftime("%Y-%m-%d %H:%M"), "summary": summarize(rows), "rows": rows}
    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    return result


def load_last() -> dict | None:
    try:
        with open(RESULT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    from extract import extract_with_meta
    res = run(extract_with_meta, progress=lambda r: print("ok  " if r["correct"] else "MISS", r["message"], r["wrong_fields"] or ""))
    s = res["summary"]
    for name, v in s.get("by_set", {}).items():
        print(f"  {name}: {v['correct']}/{v['total']}")
    print(f"\n{s['correct']}/{s['total']} correct ({s['accuracy']}%). Wrong: {s['wrong']}, "
          f"grammar guard corrected {s['guard_fixed']}, stopped before the ledger: {s['caught_before_ledger']}, wrote wrong data: {s['wrong_reached_ledger']}.")
    print(f"Latency avg {s['avg_latency_ms']} ms, p95 {s['p95_latency_ms']} ms. Tokens {s['prompt_tokens']} in / {s['completion_tokens']} out.")
