/* KhataPilot site. No dependencies. Motion is transform/opacity only; everything has a reduced-motion path. */
(() => {
  const root = document.documentElement;
  root.classList.add("js");
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const ease = t => 1 - Math.pow(1 - t, 3);
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  /* ---------------------------------------------------------------- nav */
  const nav = $("#nav"), links = $("#navLinks"), blob = $(".nav__blob");
  $("#navToggle").addEventListener("click", () => {
    const open = nav.dataset.open !== "true";
    nav.dataset.open = open; $("#navToggle").setAttribute("aria-expanded", open);
  });
  links.addEventListener("click", e => { if (e.target.closest("a")) { nav.dataset.open = "false"; $("#navToggle").setAttribute("aria-expanded", "false"); } });

  if (matchMedia("(hover:hover) and (pointer:fine)").matches) {
    nav.addEventListener("pointermove", e => nav.style.setProperty("--sheen-x", e.clientX - nav.getBoundingClientRect().left + "px"));
  }
  const moveBlob = a => {
    if (reduce || innerWidth <= 820) return;
    const lr = links.getBoundingClientRect(), r = a.getBoundingClientRect();
    blob.style.width = r.width + "px";
    blob.style.transform = `translate(${r.left - lr.left}px,-50%)`;
    blob.classList.remove("is-on"); void blob.offsetWidth; blob.classList.add("is-on");
  };
  $$("a", links).forEach(a => {
    a.addEventListener("pointerenter", () => moveBlob(a));
    a.addEventListener("focus", () => moveBlob(a));
  });
  links.addEventListener("pointerleave", () => blob.classList.remove("is-on"));
  links.addEventListener("focusout", e => { if (!links.contains(e.relatedTarget)) blob.classList.remove("is-on"); });

  const darkEls = $$("[data-dark]");
  const sections = $$("main section[id]").filter(s => $(`.nav__links a[href="#${s.id}"]`));
  function onScroll() {
    nav.classList.toggle("is-scrolled", scrollY > 24);
    const y = 52;
    nav.classList.toggle("nav--dark", darkEls.some(d => { const r = d.getBoundingClientRect(); return r.top <= y && r.bottom >= y; }));
    let cur = null;
    sections.forEach(s => { const r = s.getBoundingClientRect(); if (r.top <= innerHeight * .4 && r.bottom > innerHeight * .4) cur = s.id; });
    $$("a", links).forEach(a => a.classList.toggle("is-current", a.getAttribute("href") === "#" + cur));
    expand();
  }

  /* ------------------------------------------------- decrypt text reveal */
  const GLYPHS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghkmnpqrstuvwxyz0123456789₹#%&";
  function decrypt(el, ms = 760) {
    if (reduce || el.dataset.done) return;
    el.dataset.done = "1";
    const final = el.textContent;
    el.setAttribute("aria-label", final);
    const words = final.split(" ");
    el.textContent = "";
    const spans = words.map((w, i) => {
      const s = document.createElement("span");
      s.className = "dc"; s.setAttribute("aria-hidden", "true"); s.textContent = w;
      el.append(s); if (i < words.length - 1) el.append(" ");
      return s;
    });
    const widths = spans.map(s => s.getBoundingClientRect().width);   // freeze layout so wrapping never jumps
    spans.forEach((s, i) => { s.style.width = widths[i] + "px"; s.style.whiteSpace = "nowrap"; });
    const t0 = performance.now(), total = final.replace(/ /g, "").length;
    const settle = () => spans.forEach((s, i) => { s.textContent = words[i]; s.style.width = ""; s.style.whiteSpace = ""; });
    setTimeout(settle, ms + 250);                                      // safety net if frames are throttled
    (function tick(now) {
      const p = clamp((now - t0) / ms), done = Math.floor(ease(p) * total);
      let n = 0;
      spans.forEach((s, i) => {
        s.textContent = [...words[i]].map(c => (n++ < done ? c : GLYPHS[(Math.random() * GLYPHS.length) | 0])).join("");
      });
      if (p < 1) requestAnimationFrame(tick);
      else spans.forEach((s, i) => { s.textContent = words[i]; s.style.width = ""; s.style.whiteSpace = ""; });
    })(t0);
  }
  /* decrypt a short string into a node (used by the live demo) */
  function scrambleInto(node, final, ms = 520) {
    if (reduce) { node.textContent = final; return; }
    const t0 = performance.now();
    setTimeout(() => (node.textContent = final), ms + 250);
    (function tick(now) {
      const p = clamp((now - t0) / ms), done = Math.floor(ease(p) * final.length);
      node.textContent = [...final].map((c, i) => (i < done || c === " " ? c : GLYPHS[(Math.random() * GLYPHS.length) | 0])).join("");
      if (p < 1) requestAnimationFrame(tick); else node.textContent = final;
    })(t0);
  }

  /* ------------------------------------------------ reveal on enter, once */
  const rvTargets = [".try__head", ".chat", ".read", ".step", ".sec__lede", ".lang", ".faq details", ".notes p", ".stat", ".cmd", ".close__small"];
  rvTargets.forEach(sel => $$(sel).forEach((el, i) => { el.classList.add("rv"); el.style.setProperty("--i", i % 6); }));
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(es => es.forEach(e => {
      if (!e.isIntersecting) return;
      const el = e.target; io.unobserve(el);
      if (el.matches("[data-decrypt]")) decrypt(el);
      if (el.classList.contains("rv")) el.classList.add("in");
      if (el.matches(".stat")) countUp($(".stat__n", el));
      if (el.id === "try" || el.matches(".try")) startDemo();
    }), { threshold: .18, rootMargin: "0px 0px -6% 0px" });
    $$(".rv, [data-decrypt], .try").forEach(el => io.observe(el));
    // hero headline decrypts on load
    const h1 = $(".hero__title"); if (h1) { io.unobserve(h1); requestAnimationFrame(() => decrypt(h1, 900)); }
  } else { $$(".rv").forEach(el => el.classList.add("in")); startDemo(); }

  /* ------------------------------------------------------------ counters */
  function countUp(el) {
    if (!el || reduce || el.dataset.done) return;
    el.dataset.done = "1";
    const final = el.textContent, target = +el.dataset.count, suffix = el.dataset.suffix || "", t0 = performance.now();
    (function tick(now) {
      const p = clamp((now - t0) / 1100);
      el.textContent = Math.round(ease(p) * target) + suffix;
      if (p < 1) requestAnimationFrame(tick); else el.textContent = final;
    })(t0);
  }

  /* ------------------------------------------------- the live thing: demo
     These are real Nemotron answers (Nemotron-3-Nano on Nebius Token Factory) saved from our evaluation run. */
  const MSGS = [
    { m: "Kapoor traders ne 5,000 bhej diye", intent: "Payment received", who: "Kapoor traders", amount: "Rs 5,000", ms: 3964,
      checks: ["Intent is a known type", "Amount is a positive number", "Payer is named"],
      result: "Kapoor traders now owes Rs 5,000 less.", small: "Applied to their oldest unpaid bill first." },
    { m: "Mehta wholesale ko 8000 dena hai, 5 tarikh tak", intent: "We owe money", who: "Mehta wholesale", amount: "Rs 8,000", due: "5 Nov", ms: 4601,
      checks: ["Intent is a known type", "Amount is a positive number", "Due date is a real date"],
      result: "We owe Mehta wholesale Rs 8,000, due 5 Nov.", small: "Added to what you pay suppliers." },
    { m: "Ramesh bhai 15 kg chawal aur 5 kg dal, saturday tak", intent: "Order", who: "Ramesh bhai", items: "15 kg chawal, 5 kg dal", due: "17 Oct", ms: 12095,
      checks: ["Intent is a known type", "Quantities are positive numbers", "Due date is a real date"],
      result: "Ramesh bhai's order is in: 15 kg chawal and 5 kg dal.", small: "Stock goes down. The owner is warned if it runs short." },
    { m: "Payment kar diya hai 12,000 ka, check kar lena", intent: "Payment received", who: "nobody named", amount: "Rs 12,000", ms: 2467, hold: true,
      checks: ["Intent is a known type", "Amount is a positive number", "Payer is not named"],
      result: "Held for you. Rs 12,000 was paid, but nobody is named.", small: "Code never guesses a customer. You pick who it was." },
    { m: "Namak ke packet leak ho rahe hain, Gupta store ne complaint ki", intent: "Complaint", who: "Gupta store", items: "packet namak", ms: 3237, hold: true,
      checks: ["Intent is a known type", "Complaints never touch the ledger"],
      result: "Held for you. Gupta store has a complaint about leaking namak packets.", small: "Complaints always wait for a person." },
  ];
  const chatLog = $("#chatLog"), chips = $("#chips"), fields = $("#fields"), checksEl = $("#checks"), result = $("#result"), readTime = $("#readTime");
  let run = 0, started = false;
  const TICK = '<svg viewBox="0 0 12 12"><path d="M2 6.5l2.6 2.6L10 3.5"/></svg>';

  MSGS.forEach((d, i) => {
    const b = document.createElement("button");
    b.className = "chip"; b.type = "button"; b.textContent = d.m; b.setAttribute("aria-pressed", "false");
    b.addEventListener("click", () => play(i));
    chips.append(b);
  });

  async function play(i) {
    const id = ++run, d = MSGS[i];                                   // a newer tap cancels the one in flight
    $$(".chip", chips).forEach((c, j) => c.setAttribute("aria-pressed", String(j === i)));
    fields.replaceChildren(); checksEl.replaceChildren(); readTime.textContent = ""; result.className = "read__result"; result.textContent = "";
    chatLog.replaceChildren(el("div", "bubble", d.m));
    const typing = el("div", "typing"); typing.innerHTML = "<i></i><i></i><i></i>"; chatLog.append(typing);
    await sleep(reduce ? 0 : 650); if (id !== run) return;
    typing.remove();

    const rows = [["Intent", d.intent], ["Who", d.who], d.amount && ["Amount", d.amount], d.items && ["Items", d.items], d.due && ["Due", d.due]].filter(Boolean);
    for (const [k, v] of rows) {
      const row = el("div"); const dt = el("dt", "", k), dd = el("dd");
      row.append(dt, dd); fields.append(row);
      requestAnimationFrame(() => row.classList.add("in"));
      scrambleInto(dd, v);
      await sleep(reduce ? 0 : 170); if (id !== run) return;
    }
    readTime.textContent = `Nemotron took ${(d.ms / 1000).toFixed(1)} s on Nebius (saved from a real run).`;
    await sleep(reduce ? 0 : 420); if (id !== run) return;
    for (const [n, c] of d.checks.entries()) {
      const bad = d.hold && n === d.checks.length - 1;
      const li = el("li"); li.innerHTML = `<span class="tick ${bad ? "tick--hold" : ""}">${bad ? '<svg viewBox="0 0 12 12"><path d="M6 3v4M6 9.4v.1"/></svg>' : TICK}</span>`;
      li.append(document.createTextNode(c)); checksEl.append(li);
      requestAnimationFrame(() => li.classList.add("in"));
      await sleep(reduce ? 0 : 260); if (id !== run) return;
    }
    await sleep(reduce ? 0 : 200); if (id !== run) return;
    result.className = "read__result" + (d.hold ? " is-held" : "");
    result.innerHTML = ""; result.append(document.createTextNode(d.result), el("small", "", d.small));
    requestAnimationFrame(() => result.classList.add("in"));
  }
  function el(tag, cls = "", text = "") { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; }
  function startDemo() { if (started) return; started = true; play(0); }

  /* ----------------------------------------------- photo expansion (scroll-linked) */
  const exp = $(".expand"), frame = $("#expandFrame");
  function expand() {
    if (!exp || reduce) return;
    const r = exp.getBoundingClientRect(), travel = exp.offsetHeight - innerHeight;
    const p = clamp(-r.top / travel);
    const grow = ease(clamp(p / .42)), shrink = clamp((p - .86) / .14);
    const s = lerp(.6, 1, grow) - .08 * ease(shrink);
    const t = clamp((p - .4) / .16) * (1 - clamp((p - .88) / .08));
    frame.style.setProperty("--s", s.toFixed(4));
    frame.style.setProperty("--t", t.toFixed(3));
  }

  /* ------------------------------------------------------------- languages */
  const BRIEF = {
    english: "Namaste. Today is 2026-10-29. Money to collect: Rs 7,000 from Kapoor traders (due 2026-10-23), Rs 5,000 from Kapoor traders (due 2026-10-25), Rs 4,500 from Sharma ji (due 2026-10-27). Total to collect is Rs 16,500. Money to pay suppliers: Rs 8,000 to Mehta wholesale on 2026-11-01. No stock needs reorder. Messages needing your decision: 0. First, call the customers who owe us.",
    hinglish: "Namaste! Aaj Rs 7,000 vasool karna hai Kapoor traders se, Rs 5,000 phir Rs 4,500 Sharma ji se. Rs 8,000 pay Mehta wholesale by 2026-11-01. Stock level fine, kuch reorder nahi. 0 messages pending. Pehle Kapoor traders ko call karo.",
    hindi: "नमस्ते! आज Rs 16,500 वसूल करना है। सबसे पहले Kapoor traders का Rs 7,000, जो 2026-10-23 से बाकी है। फिर Kapoor traders का Rs 5,000, जो 2026-10-25 से बाकी है। फिर Sharma ji का Rs 4,500, जो 2026-10-27 से बाकी है। बकाया कुल Rs 16,500 है। अब हमें Rs 8,000 Mehta wholesale को 2026-11-01 को देना है। स्टॉक ठीक है, कोई रीऑर्डर नहीं। निर्णय के लिए कोई संदेश नहीं है। पहले Kapoor traders से Rs 7,000 वसूल करें।"
  };
  const tabs = $$(".lang__tabs button"), ink = $(".lang__ink"), text = $("#langText");
  function placeInk(b, instant) {
    if (instant) ink.style.transition = "none";
    ink.style.width = b.offsetWidth + "px"; ink.style.transform = `translateX(${b.offsetLeft - 5}px)`;
    if (instant) { void ink.offsetWidth; ink.style.transition = ""; }
  }
  function setLang(b, first) {
    tabs.forEach(t => t.setAttribute("aria-selected", String(t === b)));
    placeInk(b, first);
    const apply = () => { text.textContent = BRIEF[b.dataset.lang]; text.lang = b.dataset.lang === "hindi" ? "hi" : "en"; text.classList.remove("is-out"); };
    if (first || reduce) apply(); else { text.classList.add("is-out"); setTimeout(apply, 180); }
  }
  tabs.forEach(b => b.addEventListener("click", () => setLang(b)));
  document.fonts && document.fonts.ready.then(() => placeInk(tabs.find(t => t.getAttribute("aria-selected") === "true"), true));
  setLang(tabs[0], true);
  const reflowInk = () => placeInk(tabs.find(t => t.getAttribute("aria-selected") === "true"), true);
  addEventListener("resize", reflowInk);
  if ("ResizeObserver" in window) new ResizeObserver(reflowInk).observe($(".lang__tabs"));   // fonts loading changes tab widths

  /* ------------------------------------------------------------------ copy */
  $("#copyBtn").addEventListener("click", async e => {
    const btn = e.currentTarget, txt = $("#cmdText").textContent;
    try { await navigator.clipboard.writeText(txt); } catch { const r = document.createRange(); r.selectNodeContents($("#cmdText")); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }
    btn.textContent = "Copied"; setTimeout(() => (btn.textContent = "Copy"), 1600);
  });

  /* ------------------------------------------------------------- boot */
  let ticking = false;
  addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(() => { onScroll(); ticking = false; }); } }, { passive: true });
  addEventListener("resize", onScroll);
  onScroll();
})();
