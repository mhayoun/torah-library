#!/usr/bin/env python3
"""
build_keywords_list.py
-----------------------
One-off migration: derives the distinct AI-topic keyword list from the
videos already stored in cours_full and writes it to the keywords_list
Redis key, without needing to wait for the next sync (or for someone to
hit GET /api/keywords and trigger the endpoint's own self-heal fallback).

Run this once right after deploying the keywords_list feature so the
frontend's search listbox is populated immediately instead of only on
the first /api/keywords request after deploy.

After that, keywords_list stays fresh on its own — it's rebuilt
automatically by every daily sync (main.py's _build_response) and by
the transcript backfill script (backfill_halacha_transcripts.py), so
you should not need to run this again except after a manual Redis wipe.

Usage:
    python3 build_keywords_list.py
    python3 build_keywords_list.py --dry-run
"""

import argparse
import asyncio
import json

from dotenv import load_dotenv
load_dotenv()

from main import get_redis, _extract_keywords, _save_keywords_list


async def run(dry_run: bool):
    r = await get_redis()
    try:
        raw = await r.get("cours_full")
        all_videos = json.loads(raw) if raw else []
        print(f"cours_full: {len(all_videos)} video(s) total")

        videos_with_topics = [v for v in all_videos if v.get("topics")]
        print(f"videos with topics: {len(videos_with_topics)}")

        keywords = _extract_keywords(all_videos)
        print(f"distinct keywords found: {len(keywords)}")
        for k in keywords[:20]:
            print(f"  - {k}")
        if len(keywords) > 20:
            print(f"  … and {len(keywords) - 20} more")

        if dry_run:
            print("\nDry run — nothing written to Redis.")
            return

        await _save_keywords_list(r, all_videos)
        print(f"\nDone. keywords_list written to Redis ({len(keywords)} keyword(s)).")

    finally:
        await r.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build keywords_list in Redis from the existing cours_full data."
    )
    parser.add_argument("--dry-run", action="store_true",
                         help="Only show what would be written; write nothing")
    args = parser.parse_args()

    asyncio.run(run(args.dry_run))
