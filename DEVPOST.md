# KhataPilot: a back-office agent for small shops that run on WhatsApp

## The problem
In India and other emerging markets, many small traders run their business on chat messages. In India the messages are
Hinglish: *"Kapoor traders ne 3,000 bhej diye"*, *"10 dabba tel chahiye, Gupta store"*. Money owed lives in the owner's head or
a paper khata. Reminders get forgotten, stock runs out, and the owner spends the evening reconciling.

## What it does
KhataPilot reads those messages with NVIDIA Nemotron on Nebius Token Factory, keeps the ledger (stock, money owed to you, money you
owe), and tells the owner each morning what to do first. At close of day it freezes balances and writes spreadsheets. Next
morning every customer who owes money has a one-click WhatsApp reminder ready. **A person presses send every time.**

## Why it is trustworthy
**The model reads, code decides, you send.** Nemotron only turns language into structured data. Code validates every field
before it touches the ledger; unclear messages go to a "needs your decision" queue. Customer reminders contain money, so they
are built by code with no model involved. Every number in a model-written briefing is checked against the ledger, and the text
is discarded if one is wrong.

## How we know it works
48 hand-labelled Hinglish messages, scored automatically (`python evalrun.py`), 20 of them written after the prompt was frozen.
Nemotron plus our validation code scores **92% to 98%** across four runs (held-out set 85% to 95%). Two Hindi grammar guards
bring it to 48/48 in three runs, but we wrote them after seeing the misses, so we treat that as in-sample and say so.
Switching Nemotron's reasoning off was about 7x faster but fell to 57%, so we keep it on. The dashboard shows per-message
latency, tokens and cost per 1,000 messages.

## Built with
Nemotron-3-Nano-30B-A3B on Nebius Token Factory (OpenAI-compatible API), Python standard library, SQLite, a single-file web UI.

## Hinglish is just the hardest case
The same pipeline works for any code-mixed language. The briefing already switches between English, Hinglish and Hindi.

## What's next
Invoice photos (vision model), item-to-supplier mapping, WhatsApp Business API with owner approval, Hindi voice notes through a
server-side speech model, multi-shop support.
