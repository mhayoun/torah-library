#!/usr/bin/env python3
"""
backfill_document_texts.py
----------------------------
One-off manual backfill: extracts text from the PDF/DOCX handouts already
matched to השיעור השבועי videos (see drive_documents_utils.py) but not
yet indexed for search (see doc_text_utils.py / GET /api/search-docs).

The daily sync only extracts a handful of new handouts per run
(MAX_AUTO_DOC_TEXT, default 5) to avoid blowing the Vercel timeout — this
script has no such cap by default, so it's the way to catch up a large
backlog (e.g. right after this feature was first deployed, with hundreds
of already-matched handouts pending).

It always picks up where it left off — videos already present in
doc_texts_all are skipped — so it's safe to just re-run it with a smaller
--limit repeatedly instead of risking one huge run timing out.

Usage:
    python3 backfill_document_texts.py            # process everything pending
    python3 backfill_document_texts.py --limit 20
    python3 backfill_document_texts.py --dry-run
"""

import argparse
import asyncio
import json
import sys

from dotenv import load_dotenv
load_dotenv()

from redis.exceptions import RedisError

from main import get_redis
from doc_text_utils import build_doc_texts_index


async def _connect_with_retry(attempts: int = 3, delay: float = 2.0):
    last_err = None
    for attempt in range(1, attempts + 1):
        r = await get_redis()
        try:
            await r.ping()
            return r
        except RedisError as e:
            last_err = e
            await r.aclose()
            print(f"⚠️  Redis connection attempt {attempt}/{attempts} failed "
                  f"({type(e).__name__}: {e}); retrying in {delay:.0f}s...")
            await asyncio.sleep(delay)
    print(f"❌ Could not reach Redis after {attempts} attempts: {last_err}")
    sys.exit(1)


async def run(limit: int | None, dry_run: bool):
    r = await _connect_with_retry()
    try:
        full_raw = await r.get("cours_full")
        all_videos = json.loads(full_raw) if full_raw else []
        print(f"cours_full: {len(all_videos)} video(s) total")

        existing_raw = await r.get("doc_texts_all")
        existing = json.loads(existing_raw) if existing_raw else {}
        print(f"doc_texts_all: {len(existing)} handout(s) already indexed")

        pending = [
            v for v in all_videos
            if v.get("documents") and v.get("id") not in existing
            and (v["documents"].get("pdf") or v["documents"].get("docx"))
        ]
        print(f"{len(pending)} handout(s) still need text extraction\n")

        if not pending:
            print("Nothing to do.")
            return

        if dry_run:
            for v in pending[: limit or len(pending)]:
                print(f"  would process: {v.get('title')}  ({v.get('id')})")
            print("\nDry run — nothing written to Redis.")
            return

        print(f"Processing (limit={limit or 'unlimited'})...\n")
        doc_texts, extracted = build_doc_texts_index(all_videos, existing, max_new=limit)
        await r.set("doc_texts_all", json.dumps(doc_texts, ensure_ascii=False))

        print(f"\nDone. {extracted} handout(s) extracted and saved.")
        remaining = len(pending) - extracted
        if remaining > 0:
            print(f"{remaining} handout(s) still remain — run again to continue the backfill.")

    finally:
        await r.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill PDF/DOCX handout text extraction into doc_texts_all."
    )
    parser.add_argument("--limit", type=int, default=None,
                         help="Max number of handouts to process this run "
                              "(default: no limit — process everything pending)")
    parser.add_argument("--dry-run", action="store_true",
                         help="Only show what would be processed; write nothing")
    args = parser.parse_args()

    asyncio.run(run(args.limit, args.dry_run))
