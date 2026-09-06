#!/usr/bin/env python3
"""
backfill_drive_documents.py
------------------------------
One-off manual backfill: matches PDF/DOCX handouts already sitting in the
Drive folder tree (see drive_documents_utils.py) to existing השיעור השבועי
videos in cours_full that don't have a `documents` field yet.

Normally this matching happens automatically during the daily sync
(main.py step 5c), but that only runs against Vercel's own copy of
GOOGLE_DRIVE_TOKEN_JSON, and only for videos that are "new this sync" or
still missing `documents` at that moment. This script runs the same
matching logic directly against the shared Redis store (cours_full),
using whatever GOOGLE_DRIVE_TOKEN_JSON is set locally in .env - handy to
verify a freshly-issued Drive token actually works, or to catch up a
backlog without waiting for the next cron run / a Vercel redeploy.

It always re-checks every השיעור השבועי video still missing `documents`
- so it's safe to just re-run it after uploading new handouts to Drive.

Usage:
    python3 backfill_drive_documents.py            # match + save
    python3 backfill_drive_documents.py --dry-run  # show matches, write nothing
"""

import argparse
import asyncio
import json
import sys

from dotenv import load_dotenv
load_dotenv()

from redis.exceptions import RedisError

from main import get_redis, _response_from_full

WEEKLY_LESSON_CATEGORY = "השיעור השבועי"


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


async def run(dry_run: bool):
    r = await _connect_with_retry()
    try:
        full_raw = await r.get("cours_full")
        all_videos = json.loads(full_raw) if full_raw else []
        print(f"cours_full: {len(all_videos)} video(s) total")

        pending = [
            v for v in all_videos
            if v.get("category") == WEEKLY_LESSON_CATEGORY and "documents" not in v
        ]
        print(f"{len(pending)} {WEEKLY_LESSON_CATEGORY} video(s) still missing `documents`\n")

        if not pending:
            print("Nothing to do.")
            return

        print("Building Drive folder index (this walks the whole tree once)...")
        from drive_documents_utils import build_video_documents_index
        doc_index = build_video_documents_index()
        print(f"Drive index: {len(doc_index)} video id(s) with a matched file\n")

        matched = 0
        for v in pending:
            docs = doc_index.get(v["id"])
            if docs and (docs.get("pdf") or docs.get("docx")):
                names = [docs[k]["name"] for k in ("pdf", "docx") if docs.get(k)]
                print(f"  MATCH  {v.get('title')}  ({v.get('id')})  -> {', '.join(names)}")
                if not dry_run:
                    v["documents"] = docs
                matched += 1
            else:
                print(f"  no match  {v.get('title')}  ({v.get('id')})")

        print(f"\n{matched}/{len(pending)} matched this run")

        if dry_run:
            print("\nDry run — nothing written to Redis.")
            return

        if matched == 0:
            print("Nothing new to save.")
            return

        await r.set("cours_full", json.dumps(all_videos, ensure_ascii=False))
        await _response_from_full(r, all_videos)
        print("\n✅ Saved to Redis (cours_full + cours_response rebuilt).")
        print("Run backfill_document_texts.py next to index the newly-matched handouts for search.")

    finally:
        await r.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill Drive PDF/DOCX handout matches into cours_full."
    )
    parser.add_argument("--dry-run", action="store_true",
                         help="Only show what would match; write nothing")
    args = parser.parse_args()

    asyncio.run(run(args.dry_run))
