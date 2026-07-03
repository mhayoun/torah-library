#!/usr/bin/env python3
"""
backfill_halacha_transcripts.py
--------------------------------
One-off manual backfill: attaches a Hebrew transcript + AI-extracted
topic markers (keyword + start position) to existing הלכה יומית videos
in cours_full that don't have them yet.

It always picks up where it left off — videos already marked "done" or
"no_captions" are skipped — so it's safe to just re-run it with a small
--limit repeatedly until every video is covered, instead of risking a
single huge run that burns your whole YouTube/Gemini quota (or times
out) in one go.

Between videos, it sleeps a random duration (default 3-5 minutes) —
this spreads out the transcript requests instead of hammering YouTube
back-to-back, which lowers the chance of getting IP-blocked/rate-limited
mid-run.

Usage:
    python3 backfill_halacha_transcripts.py --limit 20
    python3 backfill_halacha_transcripts.py --limit 5 --dry-run
    python3 backfill_halacha_transcripts.py --limit 50 --sleep-min 2 --sleep-max 4
"""

import argparse
import asyncio
import json
import random
import time

from dotenv import load_dotenv
load_dotenv()

from main import get_redis, _response_from_full
from halacha_transcripts import HALACHA_CATEGORY, needs_transcript, process_video_transcript


async def run(limit: int, dry_run: bool, sleep_min_minutes: float, sleep_max_minutes: float):
    r = await get_redis()
    try:
        raw = await r.get("cours_full")
        all_videos = json.loads(raw) if raw else []
        print(f"cours_full: {len(all_videos)} video(s) total")

        candidates = [
            v for v in all_videos
            if v.get("category") == HALACHA_CATEGORY and needs_transcript(v)
        ]
        print(f"{HALACHA_CATEGORY}: {len(candidates)} video(s) still need a transcript\n")

        batch = candidates[:limit]
        if not batch:
            print("Nothing to do.")
            return

        print(f"Processing {len(batch)} video(s) (limit={limit}, dry_run={dry_run})...\n")

        done = 0
        for i, video in enumerate(batch, 1):
            print(f"[{i}/{len(batch)}] {video.get('title')}  ({video.get('id')})")
            if dry_run:
                continue
            ok = process_video_transcript(video, logger=True)
            if ok:
                done += 1
            if i < len(batch) and sleep_max_minutes > 0:
                sleep_seconds = random.uniform(
                    sleep_min_minutes * 60, sleep_max_minutes * 60
                )
                print(f"   … sleeping {sleep_seconds / 60:.1f} min before the next video")
                time.sleep(sleep_seconds)

        if dry_run:
            print("\nDry run — nothing written to Redis.")
            return

        # cours_full holds these same (mutated) video dicts, so saving it
        # persists everything; then rebuild cours_response so the change
        # is visible to the frontend too, without waiting for tomorrow's
        # sync to overwrite it.
        await r.set("cours_full", json.dumps(all_videos, ensure_ascii=False))
        await _response_from_full(r, all_videos)

        print(f"\nDone. {done}/{len(batch)} video(s) successfully processed and saved.")
        remaining = len(candidates) - len(batch)
        if remaining > 0:
            print(f"{remaining} video(s) still remain — run again to continue the backfill.")

    finally:
        await r.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill הלכה יומית transcripts + AI topic markers into cours_full."
    )
    parser.add_argument("--limit", type=int, default=10,
                         help="Max number of videos to process this run (default: 10)")
    parser.add_argument("--dry-run", action="store_true",
                         help="Only show what would be processed; write nothing")
    parser.add_argument("--sleep-min", type=float, default=3.0,
                         help="Minimum minutes to pause between videos (default: 3)")
    parser.add_argument("--sleep-max", type=float, default=5.0,
                         help="Maximum minutes to pause between videos (default: 5)")
    args = parser.parse_args()

    if args.sleep_min < 0 or args.sleep_max < args.sleep_min:
        parser.error("--sleep-max must be >= --sleep-min, and both must be >= 0")

    asyncio.run(run(args.limit, args.dry_run, args.sleep_min, args.sleep_max))
