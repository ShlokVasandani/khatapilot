// Deterministic renderer: every frame is a pure function of time (window.render(t)), captured over the Chrome DevTools Protocol.
//   node render.mjs <outDir> stills 3,10,20      -> outDir/still_<t>.png
//   node render.mjs <outDir> frames [fps=30]     -> outDir/f00000.jpg ...
import { spawn } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";

const [outDir, mode, arg] = process.argv.slice(2);
mkdirSync(outDir, { recursive: true });
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9400 + Math.floor(Math.random() * 400);
const page = pathToFileURL(path.join(path.dirname(new URL(import.meta.url).pathname), process.env.PAGE || "launch.html")).href;
const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${PORT}`, "--window-size=1920,1080", "--hide-scrollbars",
  "--force-device-scale-factor=1", "--disable-gpu", `--user-data-dir=/tmp/kp-brag-${PORT}`, "about:blank"], { stdio: "ignore" });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let targets;
for (let i = 0; i < 50; i++) { try { targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(); if (targets.find(t => t.type === "page")) break; } catch {} await sleep(200); }
const ws = new WebSocket(targets.find(t => t.type === "page").webSocketDebuggerUrl);
await new Promise(r => (ws.onopen = r));
let id = 0; const pend = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } };
const send = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async expr => (await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;

await send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
await send("Page.enable"); await send("Page.navigate", { url: page });
for (let i = 0; i < 100; i++) { if (await ev("window.ready === true")) break; await sleep(200); }
await sleep(800); // let web fonts settle

const shot = async (t, file, fmt) => {
  await ev(`window.render(${t})`);
  const r = await send("Page.captureScreenshot", fmt === "png" ? { format: "png" } : { format: "jpeg", quality: 93 });
  writeFileSync(file, Buffer.from(r.result.data, "base64"));
};
if (mode === "stills") for (const t of arg.split(",")) await shot(+t, `${outDir}/still_${t}.png`, "png");
else {
  const fps = +(arg || 30), total = await ev("window.TOTAL") || 51.5, n = Math.round(total * fps);
  for (let f = 0; f < n; f++) { await shot(f / fps, `${outDir}/f${String(f).padStart(5, "0")}.jpg`, "jpg"); if (f % 150 === 0) console.log("frame", f, "/", n); }
}
ws.close(); chrome.kill();
process.exit(0);
