"""
Build a narrated walkthrough video (about 2:45) of KhataPilot from real screens of the hosted demo.

It is NOT a live screen recording: frames are screenshots of the demo-mode dashboard (real saved Nemotron outputs) and the
website, with captions and a synthetic voice (macOS `say`). Needs macOS, Google Chrome and ffmpeg.

    python -m http.server 8130 --directory _pages &    # after: python tools/build_pages.py
    python tools/make_video.py                         # writes /tmp-style work dir, then video/khatapilot-demo.mp4
"""
import html, os, subprocess, sys, shutil, json, math
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = os.environ.get("KP_VIDEO_DIR", os.path.join(ROOT, "video"))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "http://127.0.0.1:8130"
VOICE, RATE = "Rishi", 172
os.makedirs(W + "/frames", exist_ok=True); os.makedirs(W + "/clips", exist_ok=True); os.makedirs(W + "/audio", exist_ok=True)
sh = lambda *a, **k: subprocess.run(a, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **k)

def shot(name, url, w=1920, h=2700, transparent=False, budget=9000, still=False):
    out = f"{W}/frames/{name}.png"
    args = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--blink-settings=preferredColorScheme=1",
            f"--window-size={w},{h}", f"--virtual-time-budget={budget}", f"--screenshot={out}"]
    if transparent: args.append("--default-background-color=00000000")
    if still: args.append("--force-prefers-reduced-motion")   # site animations render in their final state
    sh(*args, url); return out

def crop(src, y, dst, h=1080):
    sh("ffmpeg", "-y", "-i", src, "-vf", f"crop=1920:{h}:0:{y}", dst); return dst

def caption(name, text):
    page = f"{W}/frames/{name}.html"
    open(page, "w").write(f"""<html><body style="margin:0;background:transparent;width:1920px;height:1080px;position:relative">
<div style="position:absolute;left:0;right:0;bottom:0;background:rgba(15,15,14,.94);color:#fff;font:600 38px/1.25 -apple-system,Inter,Helvetica,sans-serif;padding:30px 72px">{html.escape(text)}</div></body></html>""")
    return shot(name, "file://" + page, 1920, 1080, True, 1500)

D = f"{BASE}/demo/"
print("capturing frames")
shot("site", BASE + "/", 1920, 4200, budget=9000, still=True)
shot("A", D + "#seed"); shot("B", D + "#loaded&raw&msg=Kapoor%20traders%20ne%203%2C000%20bhej%20diye&brief=english")
shot("C", D + "#closed&open&brief=hindi&drafts"); shot("Dh", D + "#loaded&brief=hinglish")
F = lambda n: f"{W}/frames/{n}.png"
pieces = {  # name: (source, crop y)
    "hero": ("site", 0), "try": ("site", 680), "trace": ("B", 1180), "overview": ("B", 0), "brief_en": ("B", 0),
    "brief_hi_in": ("Dh", 0), "brief_hi": ("C", 0), "send": ("C", 0), "acc": ("B", 1470), "outro": ("site", 0)}
for k, (src, y) in pieces.items(): crop(F(src), y, f"{W}/frames/{k}.crop.png")

SEGS = [  # (caption, narration, [pieces])
 ("KhataPilot: WhatsApp in, ledger and briefing out",
  "Small shops in India run on WhatsApp messages written in Hinglish. The owner keeps the books in their head. KhataPilot reads those messages, keeps the ledger, and gets the day's reminders ready. A person presses send on everything.", ["hero"]),
 ("Nemotron reads. Code checks.",
  "Here is the idea. A message like, Kapoor traders ne three thousand bhej diye, goes to NVIDIA Nemotron on Nebius Token Factory. It comes back as structured data: who, what, and how much. Then our code checks every field before the ledger changes.", ["try"]),
 ("Every message: reading, raw JSON, time and tokens",
  "In the dashboard, every message shows exactly how it was read: a plain English reading, the raw JSON from Nemotron, the time, and the tokens. This hosted demo replays real outputs saved from our runs, so it costs nothing to try.", ["trace"]),
 ("Unclear messages wait for the owner",
  "When a message is unclear, nothing is guessed. A payment with no named payer, a complaint, or a message that cannot be classified waits in a queue. The model reads, code decides, and you send.", ["overview"]),
 ("Morning briefing: English, Hinglish, Hindi",
  "Each morning Nemotron writes the briefing in the owner's own language: English, Hinglish, or Hindi. Every number is checked against the ledger before it is shown.", ["brief_en", "brief_hi_in", "brief_hi"]),
 ("Reminders are written by code. You press send.",
  "Reminders contain money, so code builds them from the closing balances, never the model. The owner presses Open WhatsApp and sends it. Supplier reorders are drafted the same way and wait for approval.", ["send"]),
 ("Model alone 92 to 98 percent. With guards 48 of 48, in-sample.",
  "We measured it. Forty eight hand labelled Hinglish messages, twenty of them written after the prompt was frozen. Nemotron plus our validation code scores ninety two to ninety eight percent across four runs. Two grammar guards bring it to forty eight of forty eight, but we wrote them after seeing the misses, so we call that in sample. With reasoning off it is seven times faster but only fifty seven percent, so we keep reasoning on. Latency and tokens per message come straight from Token Factory.", ["acc"]),
 ("github.com/ShlokVasandani/khatapilot",
  "The code is public under the MIT licence, and there is a free hosted demo. KhataPilot: WhatsApp in, ledger and briefing out, a human on every send.", ["outro"]),
]

def dur(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).strip())

vlist, alist, total = [], [], 0.0
for i, (cap, text, ps) in enumerate(SEGS):
    aiff = f"{W}/audio/s{i}.aiff"; sh("say", "-v", VOICE, "-r", str(RATE), "-o", aiff, text)
    T = dur(aiff) + 0.8; total += T
    wav = f"{W}/audio/s{i}.wav"; sh("ffmpeg", "-y", "-i", aiff, "-af", f"apad=whole_dur={T:.3f}", "-ar", "44100", "-ac", "2", wav)
    alist.append(wav)
    ov = caption(f"cap{i}", cap)
    for j, p in enumerate(ps):
        Ti = T / len(ps); n = int(Ti * 30)
        clip = f"{W}/clips/s{i}_{j}.mp4"
        vf = (f"[0:v]scale=2112:1188,zoompan=z='1+0.00045*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s=1920x1080:fps=30,"
              f"fade=t=in:st=0:d=0.3,fade=t=out:st={Ti-0.3:.2f}:d=0.3[v];[v][1:v]overlay=0:0:shortest=1,format=yuv420p")
        sh("ffmpeg", "-y", "-i", f"{W}/frames/{p}.crop.png", "-loop", "1", "-i", ov, "-filter_complex", vf, "-t", f"{Ti:.3f}", "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "20", clip)
        vlist.append(clip)
open(f"{W}/v.txt", "w").write("".join(f"file '{c}'\n" for c in vlist)); open(f"{W}/a.txt", "w").write("".join(f"file '{c}'\n" for c in alist))
sh("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", f"{W}/v.txt", "-f", "concat", "-safe", "0", "-i", f"{W}/a.txt", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", f"{W}/khatapilot-demo.mp4")
print(f"done: {W}/khatapilot-demo.mp4  ({total:.0f}s)")
