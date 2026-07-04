#!/usr/bin/env python3
"""
backfill_transcript_storage.py
-------------------------------
ONE-OFF migration script for the new `transcript:<video_id>` Redis key.

Context: before this change, only the AI-extracted topic markers
(video["topics"]) were kept — the raw transcript segments were fetched,
used, then thrown away. Videos that were already processed
(transcript_status == "done") therefore have correct topics in
cours_full, but no `transcript:<id>` key yet for the new
GET /api/transcript/{video_id} endpoint to serve.

This script does NOT touch cours_full, does NOT call Gemini/Groq, and
does NOT wipe anything. It only:
  1. Reads cours_full
  2. For each הלכה יומית video with transcript_status == "done" (and no
     transcript:<id> key yet, unless --force), re-fetches the transcript
     from YouTube (no AI call — that part is skipped entirely)
  3. Writes it to transcript:<id>

Safe to re-run: already-migrated videos are skipped unless --force is
passed, and IP-block / per-video errors stop or skip cleanly like the
other transcript scripts.

Usage:
    python3 backfill_transcript_storage.py --limit 30
    python3 backfill_transcript_storage.py --limit 5 --dry-run
    python3 backfill_transcript_storage.py --force   # re-fetch even if transcript:<id> exists
"""

import argparse
import asyncio
import json
import random
import sys

from dotenv import load_dotenv
load_dotenv()

from redis.exceptions import RedisError

from main import get_redis, _save_transcript
from halacha_transcripts import HALACHA_CATEGORY
from transcript_utils import fetch_hebrew_transcript, NoHebrewTranscript, TranscriptFetchBlocked


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


async def run(limit: int, dry_run: bool, force: bool, sleep_min: float, sleep_max: float):
    r = await _connect_with_retry()
    try:
        raw = await r.get("cours_full")
        all_videos = json.loads(raw) if raw else []
        print(f"cours_full: {len(all_videos)} video(s) total")

        candidates = [
            v for v in all_videos
            if v.get("category") == HALACHA_CATEGORY
            and v.get("transcript_status") == "done"
            and v.get("id")
        ]
        print(f"{HALACHA_CATEGORY}: {len(candidates)} video(s) already marked 'done'")

        if not force:
            # Skip anything that already has a transcript:<id> key, so
            # this script is cheap to re-run as often as needed.
            to_process = []
            for v in candidates:
                exists = await r.exists(f"transcript:{v['id']}")
                if not exists:
                    to_process.append(v)
            candidates = to_process
        print(f"{len(candidates)} video(s) still missing a transcript:<id> key\n")

        batch = candidates[:limit]
        if not batch:
            print("Nothing to do.")
            return

        print(f"Processing {len(batch)} video(s) (limit={limit}, dry_run={dry_run})...\n")

        done = 0
        for i, video in enumerate(batch, 1):
            vid_id = video.get("id")
            title = video.get("title", "")
            print(f"[{i}/{len(batch)}] {title}  ({vid_id})")

            if dry_run:
                continue

            try:
                segments, _full_text = fetch_hebrew_transcript(vid_id)
            except NoHebrewTranscript as e:
                # Shouldn't normally happen for a video already marked
                # "done", but harmless to just skip it if it does.
                print(f"   ⚠️  No Hebrew captions this time: {e}")
                continue
            except TranscriptFetchBlocked as e:
                print(f"\n🛑 {e}\n\nStopping this run early — the remaining "
                      f"{len(batch) - i + 1} video(s) would fail the same way. "
                      f"Wait a while, then just re-run the script; it skips "
                      f"whatever's already migrated.")
                break
            except Exception as e:
                print(f"   ❌ Failed to fetch transcript: {e}")
                continue

            await _save_transcript(r, video, segments)
            done += 1
            print(f"   ✅ {len(segments)} segment(s) saved to transcript:{vid_id}")

            if sleep_max > 0 and i < len(batch):
                delay = random.uniform(sleep_min, sleep_max)
                print(f"    …sleeping {delay:.1f}s before next video…")
                await asyncio.sleep(delay)

        if dry_run:
            print("\nDry run — nothing written to Redis.")
            return

        print(f"\nDone. {done}/{len(batch)} video(s) migrated to transcript:<id>.")
        remaining = len(candidates) - len(batch)
        if remaining > 0:
            print(f"{remaining} video(s) still remain — run again to continue.")

    finally:
        await r.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="One-off: populate transcript:<id> Redis keys for already-processed הלכה יומית videos."
    )
    parser.add_argument("--limit", type=int, default=30,
                         help="Max number of videos to process this run (default: 30)")
    parser.add_argument("--dry-run", action="store_true",
                         help="Only show what would be processed; write nothing")
    parser.add_argument("--force", action="store_true",
                         help="Re-fetch and overwrite even if transcript:<id> already exists")
    parser.add_argument("--sleep-min", type=float, default=3.0,
                         help="Minimum seconds to sleep between videos (default: 3)")
    parser.add_argument("--sleep-max", type=float, default=5.0,
                         help="Maximum seconds to sleep between videos (default: 5)")
    args = parser.parse_args()

    if args.sleep_min < 0 or args.sleep_max < 0:
        parser.error("--sleep-min/--sleep-max must be >= 0")
    if args.sleep_min > args.sleep_max:
        parser.error("--sleep-min cannot be greater than --sleep-max")

    asyncio.run(run(args.limit, args.dry_run, args.force, args.sleep_min, args.sleep_max))
