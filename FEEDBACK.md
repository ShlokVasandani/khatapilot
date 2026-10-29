# Nebius Token Factory / NVIDIA Nemotron feedback

**What I built:** KhataPilot, a back-office agent for Indian shops. Nemotron-3-Nano-30B-A3B on Token Factory reads Hinglish
WhatsApp messages into a ledger, writes the morning briefing, and drafts reminders for owner approval. Code validates every
extracted field, and every number in a model-written briefing is checked against the ledger.

**What worked well**
- OpenAI-compatible API: I pointed the standard `openai` Python client at Token Factory and it worked first time.
- Pay-per-token pricing was cheap in practice, so I could re-run full evaluations many times while iterating.
- The `enable_thinking` switch worked as documented and made the speed/accuracy trade-off easy to measure.
- On Nemotron itself: it is strong at Hinglish extraction once the prompt has a schema and a few examples (quantities,
  units, relative dates like "kal" and "parso", payment direction). It is weaker at staying inside the given facts when
  writing prose.

**Friction I hit**
- Reasoning on/off is a blunt choice. With reasoning off, calls were about 7x faster, but accuracy on my 28-message demo set
  fell from 96.4% to 57%, so I kept it on. A reasoning-budget setting between the two would be very useful.
- Latency with reasoning on: about 2.5 s per short call when the endpoint was quiet, up to 35 s under load. I ran my
  evaluation 4 messages at a time to keep total time reasonable.
- Not fully deterministic at temperature 0: scores on the same 48 messages ranged from 91.7% to 97.9% across four runs.
- Output reliability: at temperature 0 the model occasionally returned a misspelled enum value (e.g. `customer_ows_us`). I
  handle this with validation and retries. Native JSON-schema / constrained output would remove that code.
- Briefing grounding: even when the figures were right, briefings sometimes got details wrong: "by tomorrow" (not in the
  facts), a leaked field name (`low_stock`), and once a Hindi briefing that reversed who owes whom. This is the main reason
  I keep a number-check guard in code. A structured-output or grounding option would help.
- Hinglish generation: asked to write Hinglish, the model leaned to English until I added Hindi-heavy examples to the prompt.
- Catalog: "Public" (pay-per-token) and "Dedicated" (hourly GPU) endpoints look similar. A clearer pay-per-token badge, or a
  "billed hourly" warning on dedicated model pages, would help new users.
- Vision: the Nemotron vision model is Dedicated-only, so invoice-photo reading isn't possible on pay-per-token.

**What I'd love next**
- Serverless vision Nemotron, native structured outputs, and an Indic-language-tuned Nemotron.
