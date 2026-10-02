# Back-Office Agent for Small Businesses

Built for the Nebius x NVIDIA Global AI Hackathon.

Small shops and traders run on WhatsApp messages and paper invoices. This agent
turns that mess into structured records (stock, receivables, payables) and a
daily briefing of what needs attention: what to reorder, who owes money, and
what to do first.

## Models and infrastructure

- NVIDIA Nemotron models served on **Nebius Token Factory** (OpenAI-compatible API)
- Larger Nemotron model for reasoning and planning; smaller ones for fast
  extraction and drafting

## Status

Early scaffold. Currently working: structured extraction from Hinglish order
messages and invoice photos (`extract.py`).

Planned: inventory and dues tracking, flagging rules, drafted reminder and
reorder messages with an approval queue, daily briefing dashboard.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in key, base URL, model IDs from Nebius docs
python extract.py messages
python extract.py invoice path/to/invoice.jpg
```

## License

MIT
