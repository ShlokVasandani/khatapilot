# Demo video script (target 2:45, hard limit 3:00)

> **A ready-made 2:09 version exists:** `khatapilot-launch.mp4` (built by `tools/brag_video/`: scenes in `launch.html`, rendered by
> `render.mjs`, soundtrack from `music.py`, voice from ElevenLabs). It is a narrated walkthrough of the hosted demo using real saved Nemotron outputs. It is **not** a live screen recording and the voice
> is synthetic, so say that in the YouTube description. If you have time, recording your own live run (below) is stronger.


Record the **local app** (real Nemotron calls, proves it is live) with QuickTime: File > New Screen Recording, or Cmd+Shift+5.
Use a 1080p window, hide bookmarks/notifications, speak slowly. Upload to YouTube as **Public**.

Setup before recording:
```bash
cd ~/Downloads/nebius-ops-agent && git checkout main && git pull && source .venv/bin/activate && python app.py 8001
```
Open http://127.0.0.1:8001 and press **Reset ledger** once so the screen is clean.

| Time | Screen | Say |
|---|---|---|
| 0:00 | Website hero (https://shlokvasandani.github.io/khatapilot/) | "Small shops in India run on WhatsApp messages in Hinglish. The owner keeps the books in their head. KhataPilot reads those messages and keeps the ledger, and a person presses send on everything." |
| 0:15 | Dashboard, paste "Kapoor traders ne 3,000 bhej diye", press Add | "This is Nemotron on Nebius Token Factory, running live. It turns the message into structured data: who, what, how much." |
| 0:30 | Trace panel, open Raw model output | "Here is the exact JSON, the time and the tokens. Code then validates every field before the ledger changes." |
| 0:50 | Paste "Payment kar diya hai 12,000 ka" and the complaint "Namak ke packet leak ho rahe hain, Gupta store ne complaint ki" | "When it is unclear, nothing is guessed. A payment with no named payer and a complaint go to a queue for the owner. The model reads, code decides, you send." |
| 1:15 | Briefing: click English, then Hinglish, then Hindi | "Every morning it writes the briefing in the owner's language, and every number is checked against the ledger." |
| 1:35 | Collections: open a customer, show reminder, hover Open WhatsApp (do not send) | "Reminders contain money, so code builds them from the closing balances. The model writes none of it. The owner presses send." |
| 1:55 | Accuracy card, press Run evaluation | "We measured it: 48 hand-labelled Hinglish messages. Nemotron plus our validation scores 92 to 98 percent. With reasoning off it is seven times faster but only 57 percent, so we keep it on. Our grammar guards were written after seeing the misses, so we call the perfect score in-sample." |
| 2:20 | Nebius performance card | "Latency and tokens per message come straight from Token Factory's usage field, so the cost of running this for a shop is visible." |
| 2:30 | Live demo URL in the browser | "There is a free hosted demo that replays real outputs, and the code is public under MIT." |
| 2:40 | Website close | "KhataPilot: WhatsApp in, ledger and briefing out, a human on every send." |

YouTube description (paste):
> KhataPilot reads Hinglish WhatsApp messages with NVIDIA Nemotron on Nebius Token Factory, keeps a shop's ledger in code, and prepares reminders for the owner to send. Code: https://github.com/ShlokVasandani/khatapilot  Live demo: https://shlokvasandani.github.io/khatapilot/demo/
