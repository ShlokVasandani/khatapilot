"""
KhataPilot dashboard: a small local web app (standard library only).

    python app.py            # then open http://127.0.0.1:8000
    python app.py 8080       # another port

Everything the CLI scripts do, on one screen: paste a WhatsApp message, see the ledger
update, read the Nemotron-written briefing, approve or edit the drafted messages.
"""

import json
import os
import sys
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db
import drafts
import eod
import evalrun
import narrate

DB_PATH = "shop.db"
EOD_TIME = os.environ.get("EOD_TIME", "21:30")   # the day closes by itself at this time (HH:MM, local)
HERE = os.path.dirname(os.path.abspath(__file__))

LOCK = threading.Lock()
LOG: list[dict] = []          # recent inbox activity, newest first
BRIEF = {"text": None, "source": None, "lang": "english"}
JOB = {"running": False, "done": 0, "total": 0}
EVAL = {"running": False, "done": 0, "total": 0, "error": None}
# Running totals for the "Nebius performance" card. Prices are per 1M tokens, from settings.env (blank = hide cost).
STATS = {"messages": 0, "recorded": 0, "review": 0, "failed": 0, "latency_ms": 0, "prompt_tokens": 0, "completion_tokens": 0}
PRICE_IN = os.environ.get("PRICE_IN_PER_M", "")
PRICE_OUT = os.environ.get("PRICE_OUT_PER_M", "")


def open_db():
    conn = db.connect(DB_PATH)
    drafts.ensure(conn)
    return conn


def reset_demo() -> None:
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = open_db()
    db.seed_demo(conn)
    conn.close()
    LOG.clear()
    BRIEF.update(text=None, source=None)
    for k in STATS:
        STATS[k] = 0


def process_message(conn, msg: str) -> dict:
    """Extract one message with Nemotron and apply it to the ledger. Never raises."""
    ex, meta, failed = {}, {}, None
    try:
        from extract import extract_with_meta  # imported late so the page loads without an API key
        ex, meta = extract_with_meta(msg)
        result = db.apply_extraction(conn, msg, ex)
    except Exception as e:
        failed = str(e)
        result = db._to_review(conn, msg, {}, f"extraction failed: {e}")
    errors = db.validate(ex) if ex else []
    entry = {"message": msg, "status": result["status"], "detail": result["detail"],
             "at": time.strftime("%H:%M:%S"), "extracted": ex, "validation": errors, "failed": failed, **meta}
    LOG.insert(0, entry)
    del LOG[60:]
    STATS["messages"] += 1
    STATS["failed" if failed else "recorded" if result["status"] == "recorded" else "review"] += 1
    for k in ("latency_ms", "prompt_tokens", "completion_tokens"):
        STATS[k] += meta.get(k, 0)
    return entry


def perf() -> dict:
    n = max(STATS["messages"] - STATS["failed"], 0)
    out = dict(STATS, avg_latency_ms=int(STATS["latency_ms"] / n) if n else 0,
               auto_sent=0, cost_per_1000=None)
    try:
        if n and PRICE_IN and PRICE_OUT:
            cost = (STATS["prompt_tokens"] * float(PRICE_IN) + STATS["completion_tokens"] * float(PRICE_OUT)) / 1e6
            out["cost_per_1000"] = round(cost / n * 1000, 2)
    except ValueError:
        pass
    return out


def _eval_job() -> None:
    from extract import extract_with_meta
    try:
        EVAL.update(running=True, done=0, total=len(__import__("json").load(open(evalrun.SET_PATH, encoding="utf-8"))), error=None)
        evalrun.run(extract_with_meta, progress=lambda r: EVAL.__setitem__("done", EVAL["done"] + 1))
    except Exception as e:
        EVAL["error"] = str(e)
    finally:
        EVAL["running"] = False


def state(conn) -> dict:
    today = date.today()
    b = db.briefing(conn, today)
    dues = [dict(r) | {"overdue": bool(r["due_date"] and r["due_date"] < today.isoformat())}
            for r in conn.execute(
                "SELECT p.name AS party, d.direction, d.amount - d.paid AS remaining, d.due_date "
                "FROM dues d JOIN parties p ON p.id = d.party_id WHERE d.status='open' "
                "ORDER BY d.due_date IS NULL, d.due_date")]
    items = [dict(r) for r in conn.execute(
        "SELECT name, unit, stock_qty, reorder_level FROM items ORDER BY name")]
    return {
        "today": today.isoformat(),
        "totals": b["totals"],
        "dues": dues,
        "items": items,
        "review": [dict(r) for r in b["needs_review"]],
        "drafts": [dict(r) for r in drafts.pending(conn)],
        "collections": eod.collections(conn, today),
        "last_close": eod.last_close(conn),
        "shop_name": eod.SHOP_NAME,
        "eod_time": EOD_TIME,
        "log": LOG,
        "brief": BRIEF,
        "job": JOB,
        "perf": perf(),
        "eval": {"last": _eval_summary(), **EVAL},
        "model": os.environ.get("TEXT_MODEL", ""),
    }


def _eval_summary():
    last = evalrun.load_last()
    return last and {"at": last["at"], **last["summary"], "misses": [
        {"message": r["message"], "wrong_fields": r["wrong_fields"], "reached_ledger": r["reached_ledger"]}
        for r in last["rows"] if not r["correct"]]}


def _demo_job() -> None:
    try:
        with open(os.path.join(HERE, "demo_messages.txt"), encoding="utf-8") as f:
            messages = [l.strip() for l in f if l.strip()]
        JOB.update(running=True, done=0, total=len(messages))
        conn = open_db()
        for m in messages:
            process_message(conn, m)
            JOB["done"] += 1
        conn.close()
    finally:
        JOB["running"] = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the terminal quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode())

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "dashboard.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif self.path == "/favicon.ico":
            self._send(204, b"")
        elif self.path == "/api/state":
            with LOCK:
                conn = open_db()
                try:
                    self._json(state(conn))
                finally:
                    conn.close()
        else:
            self._send(404, b"{}")

    def do_POST(self):
        # Browsers can't send JSON cross-site without a preflight we never answer.
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._json({"error": "json only"}, 415)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._json({"error": "bad json"}, 400)
        try:
            self._json(self.route(self.path.strip("/").split("/"), data))
        except KeyError as e:
            self._json({"error": str(e)}, 404)
        except Exception as e:  # surface the problem in the UI instead of a dead button
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def route(self, parts: list[str], data: dict):
        if parts[:2] != ["api", parts[1] if len(parts) > 1 else ""]:
            raise KeyError("not found")
        action = parts[1]
        if action == "message":
            lines = [l.strip() for l in str(data.get("text", "")).splitlines() if l.strip()][:30]
            lines = [l[:500] for l in lines]
            conn = open_db()
            try:
                return {"results": [process_message(conn, l) for l in lines]}
            finally:
                conn.close()
        if action == "briefing":
            lang = data.get("lang") if data.get("lang") in narrate.LANGS else "english"
            conn = open_db()
            try:
                text, source = narrate.narrate(db.briefing(conn), lang)
            finally:
                conn.close()
            BRIEF.update(text=text, source=source, lang=lang)
            return BRIEF
        if action == "drafts" and len(parts) == 3 and parts[2] == "generate":
            conn = open_db()
            try:
                return {"new": len(drafts.generate(conn))}
            finally:
                conn.close()
        if action == "drafts" and len(parts) == 4:
            did, verb = int(parts[2]), parts[3]
            conn = open_db()
            try:
                row = conn.execute("SELECT * FROM drafts WHERE id=?", (did,)).fetchone()
                if not row:
                    raise KeyError(f"no draft {did}")
                if verb == "edit":
                    drafts.edit(conn, did, str(data.get("text", ""))[:1000])
                    return {"ok": True}
                if verb in ("approve", "reject"):
                    drafts.set_status(conn, did, "approved" if verb == "approve" else "rejected")
                    body = conn.execute("SELECT body FROM drafts WHERE id=?", (did,)).fetchone()["body"]
                    return {"ok": True, "link": drafts.whatsapp_link(body) if verb == "approve" else None}
            finally:
                conn.close()
        if action == "review" and len(parts) == 4 and parts[3] == "dismiss":
            conn = open_db()
            try:
                with conn:
                    conn.execute("UPDATE review_queue SET resolved=1 WHERE id=?", (int(parts[2]),))
            finally:
                conn.close()
            return {"ok": True}
        if action == "eod" and len(parts) == 2:
            conn = open_db()
            try:
                result = eod.close_day(conn)
            finally:
                conn.close()
            return result
        if action == "party" and len(parts) == 4 and parts[3] == "phone":
            conn = open_db()
            try:
                try:
                    return {"ok": True, "phone": eod.set_phone(conn, int(parts[2]), str(data.get("phone", "")))}
                except ValueError as e:
                    return {"error": str(e)}
            finally:
                conn.close()
        if action == "collections" and len(parts) == 4 and parts[3] == "opened":
            conn = open_db()
            try:
                eod.mark_opened(conn, int(parts[2]))
            finally:
                conn.close()
            return {"ok": True}
        if action == "eval" and len(parts) == 3 and parts[2] == "run":
            if EVAL["running"]:
                return {"error": "an evaluation is already running"}
            threading.Thread(target=_eval_job, daemon=True).start()
            return {"ok": True}
        if action == "demo" and len(parts) == 3:
            if JOB["running"]:
                return {"error": "demo is already running"}
            reset_demo()
            if parts[2] == "load":
                threading.Thread(target=_demo_job, daemon=True).start()
            return {"ok": True}
        raise KeyError("not found")


def _auto_close_loop() -> None:
    """Close the day by itself once EOD_TIME has passed and today isn't closed yet."""
    while True:
        try:
            now = time.localtime()
            if f"{now.tm_hour:02d}:{now.tm_min:02d}" >= EOD_TIME:
                with LOCK:
                    conn = open_db()
                    try:
                        if not eod.is_closed(conn, date.today()):
                            eod.close_day(conn)
                    finally:
                        conn.close()
        except Exception:
            pass
        time.sleep(30)


def main(port: int = 8000) -> None:
    if not os.path.exists(DB_PATH):
        reset_demo()
    threading.Thread(target=_auto_close_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"KhataPilot is running at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    print(f"The day closes automatically at {EOD_TIME}; spreadsheets go to the eod/ folder.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
