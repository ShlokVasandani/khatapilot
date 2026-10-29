/* KhataPilot hosted demo (no server, no API key, no cost).
   This replaces the dashboard's /api/* calls with a small in-browser stand-in that replays REAL Nemotron outputs
   saved from our own runs, pushed through the REAL ledger code at build time (tools/build_demo.py).
   Nothing here calls a model. To read any message live, run the app with your own Nebius key. */
(() => {
  const realFetch = window.fetch.bind(window);
  const norm = s => s.toLowerCase().split(/\s+/).filter(Boolean).join(" ");
  const clone = o => JSON.parse(JSON.stringify(o));
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const now = () => new Date().toTimeString().slice(0, 8);
  const DUPE = "possible duplicate: this exact message was recorded in the last 10 minutes. If it is a new one, send it again with a small change, e.g. add the time.";

  let D = null;
  const ready = realFetch("demo-data.json").then(r => r.json()).then(d => { D = d; });

  const fresh = () => ({loaded: false, closed: false, drafted: false, lang: null, extra: [], extraReview: [],
    dismissed: new Set(), drafts: null, phones: {}, opened: {}, job: {running: false, done: 0, total: 0}, ev: {running: false, done: 0, total: 48}, seenDupes: new Set()});
  let S = fresh();

  function compose() {
    const stage = S.closed ? "closed" : S.loaded ? "loaded" : "seed";
    const st = clone(D.stages[stage]);
    // while the demo messages are "being read", show them arriving one by one
    if (S.job.running) { st.log = D.stages.loaded.log.slice(D.stages.loaded.log.length - S.job.done); }
    st.log = S.extra.concat(st.log).slice(0, 60);
    st.review = st.review.filter(r => !S.dismissed.has(r.id)).concat(S.extraReview);
    st.drafts = S.drafted ? (S.drafts || (S.drafts = clone(D.stages.drafts))) : [];
    const briefs = D.stages[S.loaded ? "loaded_briefs" : "seed_briefs"];
    st.brief = S.lang ? briefs[S.lang] : {text: null, source: null, lang: "english"};
    const p = st.perf, e = S.extra;
    p.messages += e.length;
    e.forEach(x => { p[x.status === "recorded" ? "recorded" : "review"]++; p.latency_ms += x.latency_ms || 0; p.prompt_tokens += x.prompt_tokens || 0; p.completion_tokens += x.completion_tokens || 0; });
    p.avg_latency_ms = p.messages ? Math.round(p.latency_ms / p.messages) : 0;
    st.collections.forEach(c => {
      if (S.phones[c.party_id] !== undefined) { c.phone = S.phones[c.party_id]; c.link = `https://wa.me/${c.phone}?text=${encodeURIComponent(c.text)}`; }
      if (S.opened[c.party_id]) c.opened_today = true;
    });
    st.job = S.job;
    st.eval = Object.assign({}, st.eval, {running: S.ev.running, done: S.ev.done, total: S.ev.total, error: null});
    return st;
  }

  async function addLine(line) {
    const key = norm(line), rec = D.replay[key];
    let entry;
    if (rec && S.loaded && D.dupe_keys.includes(key) && !S.seenDupes.has(key)) {
      S.seenDupes.add(key);                                   // same message already in the loaded ledger: the real app holds it
      entry = Object.assign(clone(rec), {status: "review", detail: DUPE, extracted: {}, validation: [], latency_ms: 0, prompt_tokens: 0, completion_tokens: 0});
    } else if (rec) {
      entry = clone(rec);
    } else {
      entry = {message: line, status: "review", failed: null, extracted: {}, validation: [], attempts: 0,
        detail: "Demo mode replays recorded Nemotron outputs only. Pick one of the sample messages, or run KhataPilot locally with your own Nebius key to read any message."};
    }
    entry.at = now();
    S.extra.unshift(entry);
    if (entry.status === "review") S.extraReview.push({id: 9000 + S.extra.length + Math.floor(Math.random() * 1000), raw_message: entry.message, reason: entry.detail});
    await sleep(700);                                          // roughly how long a real read feels; no model is called
    return entry;
  }

  async function post(path, body) {
    const parts = path.split("/").filter(Boolean).slice(1);    // drop "api"
    const [a, b, c] = parts;
    if (a === "message") { const lines = String(body.text || "").split(/\n/).map(s => s.trim()).filter(Boolean).slice(0, 30); const r = []; for (const l of lines) r.push(await addLine(l)); return {results: r}; }
    if (a === "briefing") { S.lang = ["english", "hinglish", "hindi"].includes(body.lang) ? body.lang : "english"; await sleep(1100); return compose().brief; }
    if (a === "drafts" && b === "generate") { await sleep(900); S.drafted = true; S.drafts = null; return {new: 1}; }
    if (a === "drafts") {
      const list = S.drafts || (S.drafts = clone(D.stages.drafts)), i = list.findIndex(d => d.id === +b);
      if (i < 0) return {error: "no such draft"};
      if (c === "edit") { list[i].body = String(body.text || ""); list[i].source = "owner"; return {ok: true}; }
      const body_ = list[i].body; list.splice(i, 1);
      return {ok: true, link: c === "approve" ? "https://wa.me/?text=" + encodeURIComponent(body_) : null};
    }
    if (a === "review" && c === "dismiss") { S.dismissed.add(+b); S.extraReview = S.extraReview.filter(r => r.id !== +b); return {ok: true}; }
    if (a === "eod") {
      if (!S.loaded) return {error: "Demo mode: press Load 28 demo messages first, then close the day."};
      S.closed = true; await sleep(500);
      const t = D.stages.closed;
      return {ok: true, day: t.last_close, frozen_total: t.totals.customer_owes_us, files: []};
    }
    if (a === "party" && c === "phone") { const ph = String(body.phone || "").replace(/\D/g, ""); if (ph.length < 10) return {error: "Enter a phone number with at least 10 digits"}; S.phones[+b] = ph.length === 10 ? "91" + ph : ph; return {ok: true, phone: S.phones[+b]}; }
    if (a === "collections" && c === "opened") { S.opened[+b] = true; return {ok: true}; }
    if (a === "eval" && b === "run") {
      if (S.ev.running) return {error: "an evaluation is already running"};
      S.ev = {running: true, done: 0, total: 48};
      (async () => { while (S.ev.done < 48) { await sleep(90); S.ev.done++; } S.ev.running = false; })();
      return {ok: true};
    }
    if (a === "demo" && b === "load") {
      if (S.job.running) return {error: "demo is already running"};
      S = fresh(); S.job = {running: true, done: 0, total: 28};
      (async () => { while (S.job.done < 28) { await sleep(130); S.job.done++; } S.loaded = true; S.job = {running: false, done: 28, total: 28}; })();
      return {ok: true};
    }
    if (a === "demo" && b === "reset") { S = fresh(); return {ok: true}; }
    return {error: "not found"};
  }

  window.fetch = async (url, opts) => {
    const u = String(url);
    if (!u.startsWith("/api/")) return realFetch(url, opts);
    await ready;
    const json = o => new Response(JSON.stringify(o), {status: 200, headers: {"Content-Type": "application/json"}});
    if (u === "/api/state") return json(compose());
    let body = {}; try { body = JSON.parse((opts && opts.body) || "{}"); } catch {}
    return json(await post(u, body));
  };

  document.addEventListener("DOMContentLoaded", () => {
    const b = document.createElement("div");
    b.setAttribute("role", "note");
    b.style.cssText = "background:#141413;color:#f6f6f4;font:13px/1.45 Inter,system-ui,sans-serif;padding:9px 24px;text-align:center";
    b.innerHTML = 'Demo mode: this is the real dashboard replaying <b>real Nemotron outputs</b> saved from our runs. No model is called and no key is used, so it costs nothing. Figures change through <b>Load 28 demo messages</b> and <b>Close the day</b>. <a href="https://github.com/ShlokVasandani/khatapilot" style="color:#fff;text-decoration:underline" rel="noopener">Run the repo locally</a> to read any message live.';
    document.body.prepend(b);
  });
})();
