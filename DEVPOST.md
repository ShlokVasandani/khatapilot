# KhataPilot: Devpost submission (copy each section into the form)

**Track:** Best Apps and Agents
**Tagline:** WhatsApp in, ledger and briefing out, a human on every send.

## Elevator pitch (167 characters, limit 200)
KhataPilot reads Hinglish WhatsApp shop messages with Nemotron on Nebius, keeps the ledger in code, and preps reminders. The model reads, code decides, you press send.

## Project name
KhataPilot

## Links (fill in the video URL after uploading)
- Live demo (free, no key): https://shlokvasandani.github.io/khatapilot/demo/
- Website: https://shlokvasandani.github.io/khatapilot/
- Code (MIT): https://github.com/ShlokVasandani/khatapilot
- Demo video: https://youtu.be/0TfvFX7GkJY
- Feedback: https://github.com/ShlokVasandani/khatapilot/blob/main/FEEDBACK.md

## Inspiration
In India, many small shops and traders run on WhatsApp messages written in Hinglish: "Kapoor traders ne 3,000 bhej diye",
"10 dabba tel chahiye, Gupta store". The owner keeps the books in their head or in a paper khata, forgets who to chase, and
spends the evening reconciling. We wanted a back office that starts from the messages that already exist.

## What it does
KhataPilot reads each message with NVIDIA Nemotron on Nebius Token Factory and turns it into a ledger entry (stock, money
owed to you, money you owe). Every morning it writes a briefing in English, Hinglish or Hindi: who to chase, what to reorder,
what needs a decision. At close of day it freezes balances and writes an Excel-ready day book. Next morning each customer who
owes money has a one-click WhatsApp reminder listing their unpaid bills. **A person presses send every time. Nothing is sent
automatically.**

## How we built it
**The model reads, code decides, you send.**
- Nemotron-3-Nano-30B-A3B on Token Factory (OpenAI-compatible API) turns a message into JSON: intent, party, items, amount, date.
- Code validates every field before the ledger changes. Complaints, unclear messages and payments with no named payer wait in a
  "needs your decision" queue. Hindi grammar traps ("X **ne** bhej diye" versus "X **ko** bhej diye") are guarded in code, and a
  duplicate message within 10 minutes is held instead of applied twice.
- Customer reminders contain money, so they are built by code from the closing balances, with no model involved.
- Every number in a model-written briefing is checked against the ledger before it is shown.
- Pure Python standard library plus SQLite, a single-file dashboard, runs on one computer. Only message text and ledger figures
  for the briefing go to Token Factory.

## How we measured it
48 hand-labelled Hinglish messages (28 demo messages plus 20 written after the prompt was frozen), scored by `python evalrun.py`.
Nemotron plus our validation code scored **92% to 98%** across four runs (85% to 95% on the 20 fresh messages). Two Hindi
grammar guards bring it to 48 of 48 in three runs, but we wrote them after seeing the misses, so we call that in-sample.
Switching Nemotron's reasoning off was about 7x faster but fell to 57%, so we keep it on. The dashboard shows per-message
latency, tokens and cost per 1,000 messages.

## Challenges
- Reliability without trusting the model: we found a wrong-direction bug class ("X ka 6,500 pending hai, saturday ko denge")
  and fixed it with grammar guards rather than a longer prompt.
- Briefings can have correct figures but wrong wording. We saw an invented "by tomorrow", a leaked field name, and once a Hindi
  briefing that reversed who owes whom. The number guard cannot catch those, which we document openly.
- Testing found that pasting the same payment twice applied it twice, so we added a duplicate guard.

## Accomplishments we're proud of
A trust model a shop owner can understand (the model never writes to the books), a visible trace of how every message was read,
and an honest evaluation that reports where it fails.

## What we learned
Reasoning matters a lot for Hinglish extraction (57% without it), outputs vary slightly between runs even at temperature 0, and
the biggest quality win came from deterministic code around the model, not a bigger prompt.

## What's next
Invoice photos with a vision model, item-to-supplier mapping, the WhatsApp Business API with owner approval, server-side Hindi
speech-to-text, fine-tuning on corrected entries, and hosted multi-shop accounts.

## Built with
NVIDIA Nemotron-3-Nano-30B-A3B, Nebius Token Factory, Python, SQLite, HTML/CSS/JavaScript, GitHub Pages.

## Notes for judges
- The hosted demo replays real Nemotron outputs saved from our runs (no live model calls, no key), so it costs nothing and
  cannot be abused. Run the repo with your own Token Factory key to read any message live.
- Briefings in the demo are real unedited model outputs, chosen from several runs for correctness. Not every run is this clean.
- The project was built entirely during the submission period (first commit 2 Oct 2026).

## Image gallery (files in ~/Downloads/devpost-gallery, upload in this order)
1. `thumbnail-3x2.png`: use as the project thumbnail
2. `1-website-hero.png`: the website
3. `2-message-to-ledger.png`: a Hinglish message becoming a ledger entry
4. `3-how-each-message-was-read.png`: raw Nemotron JSON, time, tokens
5. `4-briefing-and-reminder.png`: Hindi briefing, code-built reminder, supplier draft
6. `5-accuracy-and-performance.png`: accuracy and Nebius performance

## Submission-day checklist
- [ ] Log in to Devpost and press **Join hackathon**, then **Enter a submission**
- [ ] Track: **Best Apps and Agents**
- [ ] Paste the sections above (name, pitch, story, built with, links)
- [ ] Demo video URL (public YouTube, 3 minutes or less): the narrated walkthrough is `khatapilot-launch.mp4` (2:09)
- [ ] Demo URL: https://shlokvasandani.github.io/khatapilot/demo/
- [ ] Code URL: https://github.com/ShlokVasandani/khatapilot (public, MIT shown at the top of the repo page)
- [ ] Feedback sections: paste from `FEEDBACK.md`
- [ ] "Existed before the submission period?" No: first commit 2 Oct 2026
- [ ] Press **Submit** before Oct 30, 10:00 AM Pacific (10:30 PM IST)
