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

Usage:
    python3 backfill_halacha_transcripts.py --limit 20
    python3 backfill_halacha_transcripts.py --limit 5 --dry-run
"""

import argparse
import asyncio
import json
import random
import sys

from dotenv import load_dotenv
load_dotenv()

from redis.exceptions import RedisError

from main import get_redis, _response_from_full, _save_transcript
from halacha_transcripts import HALACHA_CATEGORY, needs_transcript, process_video_transcript
from ai_keywords_utils import _get_model_candidates, QuotaExhaustedError, GeminiTransientError
from transcript_utils import TranscriptFetchBlocked


async def _connect_with_retry(attempts: int = 3, delay: float = 2.0):
    """
    get_redis() + a real round-trip (PING) so a dead/slow connection to
    Upstash is caught here with a clear message, instead of surfacing
    later as a raw TimeoutError from deep inside redis-py.
    """
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
    print(f"❌ Could not reach Redis after {attempts} attempts: {last_err}\n"
          f"   Check that REDIS_URL is correct and reachable (e.g. "
          f"`redis-cli --tls -u $REDIS_URL ping`), and that nothing on "
          f"your network is blocking port 6379.")
    sys.exit(1)


async def run(limit: int, dry_run: bool, sleep_min: float, sleep_max: float):
    print("=== Gemini model discovery ===")
    try:
        candidates = _get_model_candidates()
        if len(candidates) == 1:
            print(f"Will use: {candidates[0]}")
        else:
            print(f"Will try, in order (moving to the next on 429): {', '.join(candidates)}")
    except Exception as e:
        print(f"❌ Model discovery raised {type(e).__name__}: {e}")
    print("===============================\n")

    r = await _connect_with_retry()
    try:
        try:
            raw = await r.get("cours_full")
        except RedisError as e:
            print(f"❌ Connected, but reading 'cours_full' failed: "
                  f"{type(e).__name__}: {e}\n"
                  f"   This usually means the connection is fine but the "
                  f"link is flaky mid-request — try re-running.")
            sys.exit(1)
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
        stopped_early = False
        for i, video in enumerate(batch, 1):
            print(f"[{i}/{len(batch)}] {video.get('title')}  ({video.get('id')})")
            if dry_run:
                continue
            try:
                ok, segments = process_video_transcript(video, logger=True)
                if segments:
                    await _save_transcript(r, video, segments)
            except QuotaExhaustedError as e:
                print(f"\n🛑 {e}\n\nStopping this run early — the remaining "
                      f"{len(batch) - i + 1} video(s) in this batch would "
                      f"fail the same way. Fix the quota/billing issue above, "
                      f"then just re-run the script; it picks up where it "
                      f"left off.")
                stopped_early = True
                break
            except GeminiTransientError as e:
                print(f"\n⚠️  {e}\n   Skipping this video for now — a "
                      f"server-side hiccup like this often clears up within "
                      f"seconds, so unlike a real quota problem it's not "
                      f"worth stopping the whole batch. It'll be retried "
                      f"next time the script runs.\n")
            except TranscriptFetchBlocked as e:
                print(f"\n🛑 {e}\n\nStopping this run early — the remaining "
                      f"{len(batch) - i + 1} video(s) in this batch would "
                      f"fail the same way. Wait a while (or fix the IP-ban "
                      f"issue above), then just re-run the script; it picks "
                      f"up where it left off.")
                stopped_early = True
                break
            if ok:
                done += 1

            if sleep_max > 0 and i < len(batch):
                delay = random.uniform(sleep_min, sleep_max)
                print(f"    …sleeping {delay:.1f}s before next video…")
                await asyncio.sleep(delay)

        if dry_run:
            print("\nDry run — nothing written to Redis.")
            return

        # cours_full holds these same (mutated) video dicts, so saving it
        # persists everything; then rebuild cours_response so the change
        # is visible to the frontend too, without waiting for tomorrow's
        # sync to overwrite it. Save even on an early-stop exit so
        # whatever succeeded before the block isn't lost.
        await r.set("cours_full", json.dumps(all_videos, ensure_ascii=False))
        await _response_from_full(r, all_videos)

        if stopped_early:
            print(f"\n{done} video(s) saved before stopping early.")
            return

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
    parser.add_argument("--sleep-min", type=float, default=4.0,
                         help="Minimum seconds to sleep between videos, to "
                              "avoid hammering the YouTube/Gemini APIs "
                              "back-to-back (default: 4)")
    parser.add_argument("--sleep-max", type=float, default=5.0,
                         help="Maximum seconds to sleep between videos; the "
                              "actual delay is randomized between "
                              "--sleep-min and --sleep-max each time "
                              "(default: 5)")
    args = parser.parse_args()

    if args.sleep_min < 0 or args.sleep_max < 0:
        parser.error("--sleep-min/--sleep-max must be >= 0")
    if args.sleep_min > args.sleep_max:
        parser.error("--sleep-min cannot be greater than --sleep-max")

    asyncio.run(run(args.limit, args.dry_run, args.sleep_min, args.sleep_max))
