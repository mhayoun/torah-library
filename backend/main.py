"""
main.py
-------
FastAPI backend for the Rav Aaron Butbul's Torah lessons site.

Endpoints:
  GET /api/cours   — returns the full catalogue (Redis-cached, 6h TTL)
                     On cache miss: fetches only NEW videos from YouTube
                     and merges them with the permanent store.
  POST /api/sync   — called by the Vercel cron job every 6h (or by a
                     YouTube PubSubHubbub webhook); invalidates the short
                     cache so the next visitor triggers a fresh sync.

Redis keys:
  cours_response   — full JSON response body, TTL = CACHE_TTL (6h)
  cours_full       — permanent flat list of ALL video objects (no TTL)
  last_sync_date   — ISO-8601 timestamp of the last successful sync

Environment variables (set in Vercel or .env):
  YOUTUBE_API_KEY
  REDIS_URL        e.g. redis://default:xxx@xxx.upstash.io:6379
"""

import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis as aioredis
import ssl

from playlist_utils import get_raw_playlists, categorize_playlists
from playlist_videos_utils import enrich_structured_playlists
from debug_logger import DebugLogger

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

TARGET_URLS = [
    "https://www.youtube.com/@Rabbi_Aharon_Butbul/playlists",
    "https://www.youtube.com/@%D7%94%D7%A8%D7%91%D7%90%D7%94%D7%A8%D7%95%D7%9F%D7%91%D7%95%D7%98%D7%91%D7%95%D7%9C-%D7%A97%D7%9E/playlists",
]

CACHE_TTL = 6 * 3600  # 6 hours — same as Redis TTL

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Torah Lessons API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── Redis helpers ─────────────────────────────────────────────────────────────

async def get_redis():
    url = os.environ.get("REDIS_URL")
    if not url:
        raise HTTPException(status_code=500, detail="REDIS_URL not configured")
    return await aioredis.from_url(url, decode_responses=True)


# ── Core sync logic ───────────────────────────────────────────────────────────

async def _build_response(r) -> dict:
    """
    Fetches only NEW videos from YouTube, merges with the permanent store,
    rebuilds the catalogue, and writes all three Redis keys.
    Returns the response body dict.
    """
    # 1. Load the permanent flat list (never expires)
    existing_raw = await r.get("cours_full")
    existing: list[dict] = json.loads(existing_raw) if existing_raw else []
    existing_ids: set[str] = {v["id"] for v in existing if v.get("id")}

    last_sync = await r.get("last_sync_date")

    logger = DebugLogger()

    # 2. Discover playlists from the channel pages
    raw_playlists = get_raw_playlists(TARGET_URLS)
    structured = categorize_playlists(raw_playlists)

    # 3. Fetch videos — playlist_videos_utils already does incremental logic
    #    (it stops paginating as soon as it hits a known video ID).
    #    Pass existing_ids so it skips anything we already have.
    fresh_catalogue: dict[str, list] = enrich_structured_playlists(
        structured,
        skip_fallback=True,
        logger=logger,
        existing_ids=existing_ids,  # <-- new param (see playlist_videos_utils)
    )

    # 4. Build a flat list of ALL videos (new + old), deduplicated
    fresh_flat: list[dict] = [
        v
        for videos in fresh_catalogue.values()
        for v in videos
    ]
    fresh_ids = {v["id"] for v in fresh_flat if v.get("id")}
    new_count = len(fresh_ids - existing_ids)

    # Merge: new videos first, then old ones not already included
    all_videos: list[dict] = fresh_flat + [
        v for v in existing if v.get("id") not in fresh_ids
    ]

    # 5. Re-apply category corrections to ALL videos (including ones loaded
    #    from Redis that may have been stored with the wrong category before
    #    the rerouting fix was deployed).
    from playlist_utils import find_matching_categories
    for v in all_videos:
        title = v.get("title", "")
        current_cat = v.get("category", "אחר")
        matches = find_matching_categories(title)
        if matches:
            correct_cat = matches[0][0]
            if correct_cat != current_cat:
                v["category"] = correct_cat

    # Rebuild catalogue from the full merged flat list
    catalogue: dict[str, list] = {}
    for v in all_videos:
        cat = v.get("category", "אחר")
        catalogue.setdefault(cat, []).append(v)

    for cat in catalogue:
        catalogue[cat].sort(
            key=lambda x: x.get("upload_date") or "",
            reverse=True,
        )

    # 6. Persist
    now = datetime.now(timezone.utc).isoformat()
    response_body = {
        "catalog": catalogue,
        "total": len(all_videos),
        "new": new_count,
        "last_sync": now,
    }

    await r.set("cours_full", json.dumps(all_videos))
    await r.set("last_sync_date", now)
    await r.setex("cours_response", CACHE_TTL, json.dumps(response_body))

    logger.log_run_summary()
    log_content = logger.get_log_content()
    logger.close()

    await r.set("last_debug_log", log_content)

    return response_body


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/cours")
async def get_cours():
    """
    Main endpoint consumed by the React frontend.
    Returns immediately from Redis cache if fresh (< 6h).
    On cache miss, triggers a full incremental sync.
    """
    try:
        r = await get_redis()
        try:
            cached = await r.get("cours_response")
            if cached:
                return json.loads(cached)
            return await _build_response(r)
        finally:
            await r.aclose()
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


@app.post("/api/sync")
async def force_sync():
    """
    Called by the Vercel cron job every 6h, or by a YouTube PubSubHubbub
    webhook when a new video is published.
    Invalidates the short-lived cache so the next GET /api/cours triggers
    a fresh incremental sync.
    """
    r = await get_redis()
    try:
        await r.delete("cours_response")
        result = await _build_response(r)
        return {
            "status": "sync complete",
            "total":     result.get("total"),
            "new":       result.get("new"),
            "last_sync": result.get("last_sync"),
        }
    finally:
        await r.aclose()


@app.get("/api/status")
async def status():
    try:
        r = await get_redis()
        try:
            has_cache = await r.exists("cours_response")
            last_sync = await r.get("last_sync_date")
            full_raw = await r.get("cours_full")
            total = len(json.loads(full_raw)) if full_raw else 0
            ttl = await r.ttl("cours_response")
            return {
                "cache_active": bool(has_cache),
                "cache_ttl_seconds": ttl if ttl > 0 else None,
                "last_sync": last_sync,
                "total_videos": total,
            }
        finally:
            await r.aclose()
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


@app.get("/api/log")
async def get_log():
    """Returns the debug log from the last sync run."""
    r = await get_redis()
    try:
        from fastapi.responses import PlainTextResponse
        content = await r.get("last_debug_log")
        if not content:
            return PlainTextResponse("No log available yet. Run a sync first.")
        return PlainTextResponse(content)
    finally:
        await r.aclose()


@app.get("/api/debug-sync")
async def debug_sync():
    """
    Runs a full incremental sync and returns a detailed plain-text report.
    DRY RUN — reads from YouTube but does NOT write to Redis.

    Hit this URL in your browser to diagnose why new videos are missing:
      https://your-backend.vercel.app/api/debug-sync
    """
    from fastapi.responses import PlainTextResponse
    from playlist_videos_utils import fetch_videos_for_playlist

    lines = []
    log = lines.append

    def sep(c="─", w=68): log(c * w)

    log("=" * 68)
    log(f"  DEBUG SYNC  {datetime.now(timezone.utc).isoformat()}")
    log("=" * 68)
    log("")

    try:
        r = await get_redis()
        try:
            # ── STEP 0: Redis state ───────────────────────────────────────
            sep()
            log("STEP 0 — Redis state")
            sep()
            existing_raw = await r.get("cours_full")
            cached       = await r.get("cours_response")
            last_sync    = await r.get("last_sync_date")
            ttl          = await r.ttl("cours_response")

            existing: list[dict]    = json.loads(existing_raw) if existing_raw else []
            existing_ids: set[str]  = {v["id"] for v in existing if v.get("id")}

            log(f"  cours_full      : {len(existing)} videos stored")
            log(f"  existing_ids    : {len(existing_ids)} known IDs")
            log(f"  cours_response  : {'EXISTS (TTL ' + str(ttl) + 's)' if cached else 'MISSING'}")
            log(f"  last_sync_date  : {last_sync or 'never'}")
            if existing:
                newest = sorted(existing, key=lambda v: v.get("upload_date") or "", reverse=True)
                log(f"  newest stored   : [{newest[0].get('upload_date','?')[:10]}] {newest[0].get('title','?')}")
                log(f"  oldest stored   : [{newest[-1].get('upload_date','?')[:10]}] {newest[-1].get('title','?')}")
            log("")

            # ── STEP 1: Playlist discovery ────────────────────────────────
            sep()
            log("STEP 1 — Playlist discovery (yt-dlp)")
            sep()
            try:
                raw_playlists = get_raw_playlists(TARGET_URLS)
                structured    = categorize_playlists(raw_playlists)
            except Exception as e:
                log(f"  FAILED: {e}")
                return PlainTextResponse("\n".join(lines))

            total_pl = sum(len(v) for v in structured.values())
            log(f"  Found {total_pl} playlists across {len(structured)} categories")
            for cat, pls in structured.items():
                for pl in pls:
                    log(f"    [{cat}] {pl.get('title')} — {pl.get('url','')[:60]}")
            log("")

            # ── STEP 2: Per-playlist fetch ────────────────────────────────
            sep()
            log("STEP 2 — Per-playlist YouTube API fetch")
            sep()

            all_new_flat: list[dict] = []

            for category, playlists in structured.items():
                if category == "אחר":
                    continue
                for pl in playlists:
                    pl_url   = pl.get("url", "")
                    pl_title = pl.get("title", "")
                    log(f"\n  [{category}] {pl_title}")
                    try:
                        new_vids, mismatched = fetch_videos_for_playlist(
                            pl_url, existing_ids,
                            category=category,
                            playlist_title=pl_title,
                            logger=None,
                        )
                    except Exception as e:
                        log(f"     FAILED: {e}")
                        continue

                    log(f"     new videos found  : {len(new_vids)}")
                    log(f"     mismatched videos : {len(mismatched)}")
                    for v in new_vids[:5]:
                        log(f"       + [{v.get('upload_date','?')[:10]}] {v.get('title','?')}")
                    if len(new_vids) > 5:
                        log(f"       … and {len(new_vids) - 5} more")
                    if not new_vids and not mismatched:
                        log(f"     WARNING: 0 new videos")
                        log(f"       Possible: all videos already in cours_full, or quota exhausted")

                    all_new_flat.extend(new_vids)
                    all_new_flat.extend(v for v, _ in mismatched)

            log("")

            # ── STEP 3: Merge ─────────────────────────────────────────────
            sep()
            log("STEP 3 — Merge (dry run)")
            sep()
            fresh_ids = {v["id"] for v in all_new_flat if v.get("id")}
            new_count = len(fresh_ids - existing_ids)
            all_videos = all_new_flat + [v for v in existing if v.get("id") not in fresh_ids]
            log(f"  new from this sync  : {len(all_new_flat)}")
            log(f"  genuinely new IDs   : {new_count}")
            log(f"  total after merge   : {len(all_videos)}")
            log(f"  would write new=    : {new_count}")
            log("")

            # ── SUMMARY ───────────────────────────────────────────────────
            sep("=")
            log("SUMMARY")
            sep("=")
            if new_count > 0:
                log(f"  OK — {new_count} new video(s) detected.")
                log(f"  If live site isn't showing them -> likely Vercel timeout.")
                log(f"  Fix: maxDuration=300 in vercel.json (already applied).")
            elif len(existing_ids) == 0 and len(all_new_flat) == 0:
                log(f"  FAIL — cours_full empty AND 0 from YouTube.")
                log(f"  Check YOUTUBE_API_KEY and quota.")
            elif new_count == 0 and len(all_new_flat) > 0:
                log(f"  WARN — API returned videos but all already in cours_full.")
            else:
                log(f"  INFO — 0 new videos. No new uploads since last sync.")
            log("")

        finally:
            await r.aclose()

    except Exception as e:
        log(f"\nFATAL: {type(e).__name__}: {e}")

    return PlainTextResponse("\n".join(lines))

