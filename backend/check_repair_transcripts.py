#!/usr/bin/env python3
"""
check_repair_transcripts.py
----------------------------
Consistency checker + repairer for the four Redis structures that must
stay in sync for every הלכה יומית video:

    transcript:<id>   (per-video transcript, chunked by topic)
    cours_full[i]["topics"]   (permanent catalogue entry)
    cours_response            (derived from cours_full)
    keywords_list              (derived from cours_full)

Why this is needed
-------------------
`backfill_halacha_transcripts.py` (before this fix) only wrote
cours_full/cours_response/keywords_list ONCE, at the very end of an
entire batch run. `transcript:<id>` keys, on the other hand, are saved
per-video as soon as they're fetched. So an interrupted, killed, or
still-running batch could leave you with `transcript:<id>` keys that
exist, while the topics they represent never made it into cours_full /
cours_response / keywords_list. That script has since been patched to
checkpoint after every video, but this script exists to (a) detect and
repair any damage from previous runs, and (b) act as an ongoing health
check you can re-run any time.

For every הלכה יומית video in cours_full, this script:

  1. If `transcript:<id>` EXISTS:
       - Reconstructs the "topics" list (keyword + start) straight from
         the transcript's own chunks (no new AI/YouTube calls needed —
         the chunk boundaries in transcript:<id> ARE the topic starts).
       - Compares that against video["topics"] in cours_full.
       - If they don't match (missing, empty, or different), patches
         video["topics"] in cours_full from the transcript chunks and
         marks transcript_status = "done".

  2. If `transcript:<id>` is MISSING and the video still needs
     processing (transcript_status not in "done"/"no_captions"):
       - Fetches the transcript + runs AI topic extraction (same logic
         as the backfill script), saves transcript:<id>, and updates
         video["topics"] in cours_full.

  3. After EVERY video that was created or repaired, immediately
     persists cours_full and rebuilds cours_response + keywords_list —
     this checkpointing is the whole point: no batch, however large or
     however long the --sleep delay, can lose progress on interruption.

  4. At the end (even if nothing needed repairing), recomputes
     keywords_list from cours_full and rewrites it if it drifted, as a
     final safety net.

This script only ever fetches/calls AI for videos with NO transcript
key at all (case 2). Case 1 (repairing cours_full from an existing
transcript) never calls YouTube or Gemini/Groq — it's a pure,
inexpensive Redis-to-Redis repair.

Usage:
    python3 check_repair_transcripts.py                  # check + repair everything
    python3 check_repair_transcripts.py --dry-run         # report only, write nothing
    python3 check_repair_transcripts.py --limit 20        # cap how many MISSING-transcript
                                                           # videos get newly processed this run
    python3 check_repair_transcripts.py --skip-fetch       # only do the cheap repairs (case 1),
                                                           # never fetch new transcripts (case 2)
"""

import argparse
import asyncio
import json
import random
import sys

from dotenv import load_dotenv
load_dotenv()

from redis.exceptions import RedisError

from main import get_redis, _response_from_full, _save_transcript, _extract_keywords
from halacha_transcripts import HALACHA_CATEGORY, needs_transcript, process_video_transcript
from ai_keywords_utils import QuotaExhaustedError, GeminiTransientError
from transcript_utils import TranscriptFetchBlocked


def _topics_from_chunks(chunks: list) -> list[dict]:
    """Reconstructs a `topics` list ([{"keyword","start"}, ...]) straight
    from a saved transcript's chunks — the chunk `start` for every
    non-null keyword IS that topic's start time, by construction (see
    main.py's _chunk_transcript_by_topics)."""
    return [
        {"keyword": c["keyword"], "start": c["start"]}
        for c in (chunks or [])
        if c.get("keyword")
    ]


def _topics_equal(a: list, b: list) -> bool:
    """Order-sensitive comparison on (keyword, start) pairs only —
    ignores any extra fields either side might carry."""
    norm = lambda lst: [(t.get("keyword"), float(t.get("start", 0))) for t in (lst or [])]
    return norm(a) == norm(b)


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


async def run(limit: int, dry_run: bool, skip_fetch: bool,
              sleep_min: float, sleep_max: float, provider: str):
    r = await _connect_with_retry()
    try:
        raw = await r.get("cours_full")
        all_videos = json.loads(raw) if raw else []
        print(f"cours_full: {len(all_videos)} video(s) total")

        halacha_videos = [v for v in all_videos if v.get("category") == HALACHA_CATEGORY]
        print(f"{HALACHA_CATEGORY}: {len(halacha_videos)} video(s) to check\n")

        stats = {
            "checked": 0,
            "already_consistent": 0,
            "repaired_from_transcript": 0,   # case 1: transcript existed, cours_full was stale
            "newly_processed": 0,             # case 2: transcript didn't exist, fetched now
            "no_captions": 0,
            "errors": 0,
            "skipped_limit": 0,
        }

        async def _checkpoint(reason: str):
            if dry_run:
                return
            await r.set("cours_full", json.dumps(all_videos, ensure_ascii=False))
            await _response_from_full(r, all_videos)
            print(f"    💾 checkpoint saved ({reason})")

        newly_processed_this_run = 0
        stopped_early = False

        for video in halacha_videos:
            vid_id = video.get("id")
            title = video.get("title", "")
            if not vid_id:
                continue
            stats["checked"] += 1

            transcript_raw = await r.get(f"transcript:{vid_id}")

            # ── Case 1: transcript:<id> EXISTS — verify / repair cours_full ──
            if transcript_raw:
                try:
                    payload = json.loads(transcript_raw)
                except Exception as e:
                    print(f"⚠️  transcript:{vid_id} is corrupt JSON, skipping: {e}")
                    stats["errors"] += 1
                    continue

                expected_topics = _topics_from_chunks(payload.get("chunks"))
                current_topics = video.get("topics") or []

                needs_fix = (
                    not _topics_equal(current_topics, expected_topics)
                    or video.get("transcript_status") != "done"
                )

                if needs_fix and expected_topics:
                    print(f"🔧 [{vid_id}] transcript exists but cours_full is stale/missing "
                          f"topics — repairing from transcript:{vid_id}  ({title})")
                    video["topics"] = expected_topics
                    video["transcript_status"] = "done"
                    video.pop("transcript_error", None)
                    stats["repaired_from_transcript"] += 1
                    await _checkpoint(f"repaired {vid_id}")
                else:
                    stats["already_consistent"] += 1
                continue

            # ── Case 2: transcript:<id> MISSING — does it still need processing? ──
            if not needs_transcript(video):
                # Already marked "no_captions" — nothing to do, no transcript
                # key is expected for this video.
                stats["no_captions"] += 1
                continue

            if skip_fetch:
                stats["skipped_limit"] += 1
                continue

            if newly_processed_this_run >= limit:
                stats["skipped_limit"] += 1
                continue

            print(f"➕ [{vid_id}] no transcript:<id> found and video still needs processing "
                  f"— fetching now  ({title})")
            if dry_run:
                newly_processed_this_run += 1
                stats["newly_processed"] += 1
                continue

            try:
                ok, segments = process_video_transcript(video, logger=True, provider=provider)
                if segments:
                    await _save_transcript(r, video, segments)
                await _checkpoint(f"processed {vid_id}")
                newly_processed_this_run += 1
                if ok:
                    stats["newly_processed"] += 1
                else:
                    stats["errors"] += 1
            except QuotaExhaustedError as e:
                print(f"\n🛑 {e}\n   Stopping — quota/billing issue. Re-run this script "
                      f"later to continue; it always picks up where it left off.")
                stopped_early = True
                break
            except GeminiTransientError as e:
                print(f"\n⚠️  {e}\n   Transient hiccup — skipping this video, it'll be "
                      f"retried next run.\n")
                continue
            except TranscriptFetchBlocked as e:
                print(f"\n🛑 {e}\n   Stopping — YouTube is blocking transcript fetches "
                      f"right now. Re-run later; it picks up where it left off.")
                stopped_early = True
                break

            if sleep_max > 0:
                delay = random.uniform(sleep_min, sleep_max)
                print(f"    …sleeping {delay:.1f}s before next video…")
                await asyncio.sleep(delay)

        # ── Final safety net: recompute keywords_list from cours_full and
        #    rewrite it if it drifted from what's actually in cours_full,
        #    regardless of whether anything above needed repairing. ──
        if not dry_run:
            expected_keywords = _extract_keywords(all_videos)
            current_raw = await r.get("keywords_list")
            current_keywords = json.loads(current_raw) if current_raw else []
            if current_keywords != expected_keywords:
                await r.set("keywords_list", json.dumps(expected_keywords, ensure_ascii=False))
                print(f"\n🔧 keywords_list was stale ({len(current_keywords)} keyword(s)) "
                      f"— rebuilt to {len(expected_keywords)} keyword(s) from cours_full.")
            else:
                print(f"\n✅ keywords_list already consistent with cours_full "
                      f"({len(expected_keywords)} keyword(s)).")

        # ── Summary ──
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"  checked                  : {stats['checked']}")
        print(f"  already consistent       : {stats['already_consistent']}")
        print(f"  repaired from transcript : {stats['repaired_from_transcript']}")
        print(f"  newly processed          : {stats['newly_processed']}")
        print(f"  no_captions (skipped)    : {stats['no_captions']}")
        print(f"  errors                   : {stats['errors']}")
        print(f"  deferred (--limit hit)   : {stats['skipped_limit']}")
        if dry_run:
            print("\nDry run — nothing was written to Redis.")
        elif stopped_early:
            print("\nStopped early (quota/block) — re-run to continue.")
        if stats["skipped_limit"] > 0 and not skip_fetch:
            print(f"\n{stats['skipped_limit']} video(s) still need fetching — "
                  f"re-run (optionally with a higher --limit) to continue.")

    finally:
        await r.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Check and repair consistency between transcript:<id>, "
                    "cours_full, cours_response and keywords_list."
    )
    parser.add_argument("--limit", type=int, default=20,
                         help="Max number of MISSING-transcript videos to newly "
                              "fetch/process this run (default: 20). Repairing "
                              "cours_full from an already-existing transcript is "
                              "cheap and always unlimited.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Only report what would change; write nothing")
    parser.add_argument("--skip-fetch", action="store_true",
                         help="Only do the cheap repairs (transcript exists but "
                              "cours_full/keywords_list are stale); never fetch a "
                              "brand-new transcript for videos that don't have one yet")
    parser.add_argument("--sleep-min", type=float, default=4.0)
    parser.add_argument("--sleep-max", type=float, default=5.0)
    parser.add_argument("--provider", choices=["gemini", "groq"], default="gemini")
    args = parser.parse_args()

    asyncio.run(run(args.limit, args.dry_run, args.skip_fetch,
                     args.sleep_min, args.sleep_max, args.provider))
