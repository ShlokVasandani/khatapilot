"""
Run messages through Nemotron and into the shop database, then print the briefing.

Usage:
    python ingest.py                      # demo_messages.txt, starting from a fresh demo state
    python ingest.py my_messages.txt      # your own file, one message per line
    python ingest.py --keep               # don't reset shop.db first
"""

import argparse
import os

import db
from extract import extract_message

DB_PATH = "shop.db"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file", nargs="?", default="demo_messages.txt")
    parser.add_argument("--keep", action="store_true", help="keep the existing shop.db")
    args = parser.parse_args()

    if not args.keep and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = db.connect(DB_PATH)
    if not args.keep:
        db.seed_demo(conn)

    with open(args.file, encoding="utf-8") as f:
        messages = [line.strip() for line in f if line.strip()]

    for msg in messages:
        print(f"\n> {msg}")
        try:
            result = db.apply_extraction(conn, msg, extract_message(msg))
        except Exception as e:  # network or parse failure: queue it, keep going
            result = db._to_review(conn, msg, {}, f"extraction failed: {e}")
        tag = "OK    " if result["status"] == "recorded" else "REVIEW"
        print(f"  [{tag}] {result['detail']}")

    print("\n" + "=" * 60)
    print(db.format_briefing(db.briefing(conn)))


if __name__ == "__main__":
    main()
