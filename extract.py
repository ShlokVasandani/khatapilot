"""
Extract structured data from messy small-business inputs using Nemotron on
Nebius Token Factory.

Usage:
    python extract.py messages            # runs sample_messages.txt
    python extract.py invoice path/to.jpg # extracts from an invoice photo
"""

import base64
import json
import mimetypes
import os
import re
import sys
from datetime import date

from dotenv import load_dotenv
from openai import OpenAI

# Prefer settings.env if it exists, otherwise .env. override=True so a blank
# value in another file or the shell can never beat the one you filled in.
load_dotenv("settings.env" if os.path.exists("settings.env") else ".env", override=True)

client = OpenAI(
    base_url=os.environ["NEBIUS_BASE_URL"],
    api_key=os.environ["NEBIUS_API_KEY"],
)

TEXT_MODEL = os.environ["TEXT_MODEL"]
VISION_MODEL = os.environ.get("VISION_MODEL") or TEXT_MODEL

MESSAGE_PROMPT = """You extract structured data from messy shop messages written in \
English, Hindi, or Hinglish. Return ONLY valid JSON, no commentary.

Today is <<TODAY>> (<<WEEKDAY>>).

Schema:
{
  "intent": "order" | "payment_promise" | "payment_received" | "payment_made" | "complaint" | "inquiry" | "other",
  "party": string | null,
  "items": [{"name": string, "quantity": number | null, "unit": string | null}],
  "amount_inr": number | null,
  "due_date": "YYYY-MM-DD" | null,
  "due_date_text": string | null,
  "direction": "customer_owes_us" | "we_owe_supplier" | null,
  "notes": string | null
}

Rules:
- "name" is the product (sugar, tel, atta). Containers and measures such as kg, packet, dabba, bori, litre go in "unit", never in "name".
- Resolve relative dates against today's date: kal = tomorrow, parso = day after tomorrow, a weekday name = the next such day. Put the resolved date in "due_date" and the original words in "due_date_text".
- "direction": customer_owes_us when someone owes the shop money, we_owe_supplier when the shop owes a supplier, otherwise null.
- Numbers like "12,000" are 12000.
- "intent" is never null. If nothing else fits, use "other".
- "party" is a real person or shop name only. Forms of address such as bhai, bhaiya, ji, sir, boss, dost used on their own are NOT names, so party is null ("Ramesh bhai" or "Gupta store" are names). A payer or buyer who is not named is also null.
- Only set "due_date" when the message states a deadline or promised date. "aajkal" means "nowadays", not a date, so it gives null.
- "Payment kar diya", "paise bhej diye" and similar mean a customer has paid: intent "payment_received", direction "customer_owes_us" (even if the payer is not named).
- When the SHOP pays a supplier ("X ko 3,000 bhej diye", "X ko paise de diye"): intent "payment_made", direction "we_owe_supplier". When the shop owes a supplier ("X ko 8000 dena hai"): intent "payment_promise", direction "we_owe_supplier".
- Watch the Hindi particle: "<name> NE ... bhej diye / de diye / kar diya" means that person paid the shop, so intent "payment_received", direction "customer_owes_us". Only "<name> KO ... bhej diye" (the shop sending money to them) is "payment_made".
- Never invent values; use null when unsure.

Examples:
Message: 10 dabba tel chahiye
{"intent":"order","party":null,"items":[{"name":"tel","quantity":10,"unit":"dabba"}],"amount_inr":null,"due_date":null,"due_date_text":null,"direction":null,"notes":null}

Message: bhaiya 5 litre doodh bhej dena
{"intent":"order","party":null,"items":[{"name":"doodh","quantity":5,"unit":"litre"}],"amount_inr":null,"due_date":null,"due_date_text":null,"direction":null,"notes":null}

Message: Verma ji ka 2,000 baaki hai
{"intent":"payment_promise","party":"Verma ji","items":[],"amount_inr":2000,"due_date":null,"due_date_text":null,"direction":"customer_owes_us","notes":null}

Message: Payment bhej diya hai 8,000 ka
{"intent":"payment_received","party":null,"items":[],"amount_inr":8000,"due_date":null,"due_date_text":null,"direction":"customer_owes_us","notes":null}

Message: Anil ji ne 3,500 bhej diye
{"intent":"payment_received","party":"Anil ji","items":[],"amount_inr":3500,"due_date":null,"due_date_text":null,"direction":"customer_owes_us","notes":null}

Message: Patel traders ko 6,000 dena hai
{"intent":"payment_promise","party":"Patel traders","items":[],"amount_inr":6000,"due_date":null,"due_date_text":null,"direction":"we_owe_supplier","notes":null}

Message: Patel traders ko 2,000 bhej diye
{"intent":"payment_made","party":"Patel traders","items":[],"amount_inr":2000,"due_date":null,"due_date_text":null,"direction":"we_owe_supplier","notes":null}

Message:
"""

INVOICE_PROMPT = """Read this invoice image. Return ONLY valid JSON, no commentary.

Schema:
{
  "supplier": string | null,
  "invoice_number": string | null,
  "date": string | null,
  "items": [{"name": string, "quantity": number | null, "unit": string | null,
             "rate": number | null, "amount": number | null}],
  "total": number | null,
  "gst": number | null
}

Use null when a field is unreadable. Do not guess.
"""


def parse_json(text: str) -> dict:
    """Pull the JSON object out of a reply, even with fences or thinking text."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON found in reply: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def build_message_prompt() -> str:
    today = date.today()
    return (
        MESSAGE_PROMPT.replace("<<TODAY>>", today.isoformat())
        .replace("<<WEEKDAY>>", today.strftime("%A"))
    )


VALID_INTENTS = {"order", "payment_promise", "payment_received", "payment_made",
                 "complaint", "inquiry", "other"}
VALID_DIRECTIONS = {None, "customer_owes_us", "we_owe_supplier"}


def extract_message(message: str, attempts: int = 2) -> dict:
    """Ask the model; if it returns an unusable result (e.g. null intent), retry."""
    last = None
    for _ in range(attempts):
        resp = client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[{"role": "user", "content": build_message_prompt() + message}],
            temperature=0,
        )
        try:
            last = parse_json(resp.choices[0].message.content)
        except ValueError:
            continue
        if last.get("intent") in VALID_INTENTS and last.get("direction") in VALID_DIRECTIONS:
            return last
    if last is None:
        raise ValueError("Model did not return JSON")
    return last  # still invalid: the validator downstream sends it to review


def extract_invoice(image_path: str) -> dict:
    """Needs a vision-capable model in VISION_MODEL. Nano text models can't read images."""
    mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    resp = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": INVOICE_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
        temperature=0,
    )
    return parse_json(resp.choices[0].message.content)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in {"messages", "invoice"}:
        sys.exit(__doc__)

    if sys.argv[1] == "messages":
        with open("sample_messages.txt", encoding="utf-8") as f:
            for line in filter(None, (l.strip() for l in f)):
                print(f"\n> {line}")
                try:
                    print(json.dumps(extract_message(line), indent=2, ensure_ascii=False))
                except Exception as e:  # keep going so we see every failure
                    print(f"  FAILED: {e}")
    else:
        if len(sys.argv) < 3:
            sys.exit("Provide an image path.")
        print(json.dumps(extract_invoice(sys.argv[2]), indent=2, ensure_ascii=False))
