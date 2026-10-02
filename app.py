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
import narrate

DB_PATH = "shop.db"
HERE = os.path.dirname(os.path.abspath(__file__))

LOCK = threading.Lock()
LOG: list[dict] = []          # recent inbox activity, newest first
BRIEF = {"text": None, "source": None, "lang": "english"}
JOB = {"running": False, "done": 0, "total": 0}


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


def process_message(conn, msg: str) -> dict:
    """Extract one message with Nemotron and apply it to the ledger. Never raises."""
    try:
        from extract import extract_message  # imported late so the page loads without an API key
        result = db.apply_extraction(conn, msg, extract_message(msg))
    except Exception as e:
        result = db._to_review(conn, msg, {}, f"extraction failed: {e}")
    entry = {"message": msg, "status": result["status"], "detail": result["detail"],
             "at": time.strftime("%H:%M:%S")}
    LOG.insert(0, entry)
    del LOG[60:]
    return entry


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
        "log": LOG,
        "brief": BRIEF,
        "job": JOB,
        "model": os.environ.get("TEXT_MODEL", ""),
    }


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
        if action == "demo" and len(parts) == 3:
            if JOB["running"]:
                return {"error": "demo is already running"}
            reset_demo()
            if parts[2] == "load":
                threading.Thread(target=_demo_job, daemon=True).start()
            return {"ok": True}
        raise KeyError("not found")


def main(port: int = 8000) -> None:
    if not os.path.exists(DB_PATH):
        reset_demo()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"KhataPilot is running at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
