"""
Build demo/demo-data.json: everything the hosted, zero-cost demo needs.

The hosted demo (GitHub Pages) has no server and no API key. It replays REAL Nemotron outputs that were
saved from our own runs, pushed through the REAL ledger code (db.py, eod.py, drafts.py), so what a visitor sees
is what the app produced. Live model calls happen only here, once, when this script is run by the author:
  - 4 sample chips (cached in tools/recorded_extra.json after the first run)
  - briefings in 3 languages at 2 stages, and one reorder draft

    python tools/build_demo.py
"""
import json, os, re, shutil, sqlite3, sys, tempfile, time
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import app, db, drafts, eod, evalrun, narrate  # noqa: E402

EXTRA = os.path.join(ROOT, "tools", "recorded_extra.json")
OUT = os.path.join(ROOT, "demo", "demo-data.json")
CHIPS = ["Kapoor traders ne 3,000 bhej diye", "Sharma ji ko 5 kg chai patti bhej dena kal",
         "10 dabba tel chahiye, Gupta store", "Verma ji ka 2,500 baaki hai, 12 tarikh tak dega"]
norm = lambda s: " ".join(s.lower().split())


def recorded():
    """message -> (extraction, meta). Eval rows are real model outputs; chips are recorded once and cached."""
    rec = {}
    last = evalrun.load_last()
    for r in last["rows"]:
        meta = {k: r.get(k, 0) for k in ("latency_ms", "prompt_tokens", "completion_tokens", "attempts")}
        meta["guard_fixed"] = r.get("guard_fixed", False)
        rec[norm(r["message"])] = (r["message"], r["got"], meta)
    extra = json.load(open(EXTRA)) if os.path.exists(EXTRA) else {}
    for m in CHIPS:
        if m not in extra:
            from extract import extract_with_meta
            ex, meta = extract_with_meta(m)
            extra[m] = {"ex": ex, "meta": meta}
            json.dump(extra, open(EXTRA, "w"), ensure_ascii=False, indent=1)
        rec[norm(m)] = (m, extra[m]["ex"], extra[m]["meta"])
    return rec


def entry_for(conn, msg, ex, meta):
    result = db.apply_extraction(conn, msg, ex)
    return {"message": msg, "status": result["status"], "detail": result["detail"], "at": "", "extracted": ex,
            "validation": db.validate(ex), "failed": None, **meta}


def snapshot(conn):
    return json.loads(json.dumps(app.state(conn), ensure_ascii=False, default=str))


def good(text, source, lang):
    bad = re.search(r"low_stock|reorder_at|overdue_total|tomorrow|respectively|We need", text, re.I)
    start = text.strip().startswith(("Namaste", "नमस्ते"))
    if lang == "english":
        start = text.strip().startswith("Namaste")
    return source == "nemotron" and start and not bad


def briefings(conn):
    out = {}
    for lang in ("english", "hinglish", "hindi"):
        for _ in range(8):
            text, source = narrate.narrate(db.briefing(conn), lang)
            if good(text, source, lang):
                break
        out[lang] = {"text": text, "source": source, "lang": lang}
        print(f"  [{lang}] {source}: {text[:110]!r}")
    return out


def main():
    rec = recorded()
    tmp = tempfile.mkdtemp()
    app.DB_PATH = os.path.join(tmp, "demo.db")
    conn = app.open_db()
    db.seed_demo(conn)
    stages = {}
    app.LOG.clear()
    for k in app.STATS:
        app.STATS[k] = 0
    stages["seed"] = snapshot(conn)
    stages["seed_briefs"] = briefings(conn)

    demo_msgs = [l.strip() for l in open(os.path.join(ROOT, "demo_messages.txt"), encoding="utf-8") if l.strip()]
    for m in demo_msgs:
        _, ex, meta = rec[norm(m)]
        e = entry_for(conn, m, ex, meta)
        app.LOG.insert(0, e)
        app.STATS["messages"] += 1
        app.STATS["recorded" if e["status"] == "recorded" else "review"] += 1
        for k in ("latency_ms", "prompt_tokens", "completion_tokens"):
            app.STATS[k] += meta.get(k, 0)
    stages["loaded"] = snapshot(conn)
    stages["loaded_briefs"] = briefings(conn)

    # per-message outcome for everything else a visitor can replay, judged against the loaded ledger
    replay = {}
    for key, (m, ex, meta) in rec.items():
        mem = sqlite3.connect(":memory:"); mem.row_factory = sqlite3.Row
        conn.backup(mem)
        replay[key] = entry_for(mem, m, json.loads(json.dumps(ex)), meta)
        mem.close()

    eod.close_day(conn, out_dir=os.path.join(tmp, "eod"))
    stages["closed"] = snapshot(conn)
    ids = drafts.generate(conn)
    stages["drafts"] = [dict(r) for r in drafts.pending(conn)]
    print("drafts:", len(stages["drafts"]))

    data = {"built": time.strftime("%Y-%m-%d"), "demo_messages": demo_msgs, "chips": CHIPS, "stages": stages,
            "replay": replay, "dupe_keys": [norm(m) for m in demo_msgs]}
    json.dump(data, open(OUT, "w"), ensure_ascii=False)
    print("wrote", OUT, os.path.getsize(OUT) // 1024, "KB")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
