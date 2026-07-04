"""
main.py
-------
FastAPI backend for the Rav Aaron Butbul's Torah lessons site.

Endpoints:
  GET /api/cours    — stale-while-revalidate. Returns cours_response if
                     still fresh (< 6h). If it has expired, serves
                     straight from the permanent store (cours_full)
                     instead — no YouTube call, no live sync. Visitors
                     NEVER trigger a full sync, except on a true cold
                     start where cours_full itself is empty.
  GET /api/keywords — returns the distinct, sorted list of AI-extracted
                     topic keywords ({"keywords": [...]}), read straight
                     from the keywords_list Redis key. Lets the frontend
                     populate a search suggestions listbox without
                     downloading/scanning the whole catalogue.
  GET /api/transcript/{video_id} — returns the Hebrew transcript for
                     one video pre-split into one chunk per AI-extracted
                     topic keyword, read straight from its own
                     `transcript:<video_id>` Redis key: { "video_id",
                     "chunks": [{"keyword","start","end","text"}, ...],
                     "updated" }. Each chunk's `keyword` matches one of
                     this video's `topics[*].keyword` from /api/cours
                     (or null for the intro before the first topic), so
                     the frontend can show exactly the transcript text
                     for whichever keyword the person clicked, without
                     scanning anything. This is intentionally NOT part
                     of /api/cours — it's only fetched on demand, when
                     someone actually opens the transcript panel for a
                     video, so the main catalogue payload stays small.
  GET/POST /api/sync — called by the Vercel cron job once a day
                     (or by a YouTube PubSubHubbub webhook); runs the
                     actual incremental sync against YouTube and
                     refreshes cours_full, cours_response and
                     keywords_list. This is the ONLY regular source of
                     fresh data. GET is required because Vercel Cron
                     Jobs only ever send GET requests — POST is kept
                     for manual/webhook triggers. If CRON_SECRET is
                     set, requests must include
                     "Authorization: Bearer <CRON_SECRET>" (Vercel
                     adds this automatically for cron-triggered
                     requests).

Redis keys:
  cours_response   — full JSON response body. No TTL: it is only ever
                     overwritten by POST /api/sync (the daily cron), and
                     used as a fallback safety-net cache otherwise.
  cours_full       — permanent flat list of ALL video objects (no TTL)
  last_sync_date   — ISO-8601 timestamp of the last successful sync
  keywords_list    — sorted JSON array of every distinct AI-extracted
                     topic keyword (video["topics"][*]["keyword"]) across
                     all videos. No TTL. Rebuilt any time cours_response
                     is rebuilt (sync, cold-start fallback, or the
                     transcript backfill script), so the frontend can
                     fetch it cheaply via GET /api/keywords instead of
                     deriving it client-side from the full catalogue.
  transcript:<id>  — one key PER VIDEO (id = YouTube video id). JSON:
                     { "video_id", "chunks": [{"keyword", "start",
                     "end", "text"}, ...], "updated" }. The transcript
                     is pre-split into one chunk per AI-extracted topic
                     (using that video's `topics` start times as cut
                     points — see _chunk_transcript_by_topics), so the
                     frontend can jump straight to the text for one
                     keyword instead of scanning a flat segment list.
                     No TTL. Written once, whenever a video's transcript
                     is successfully fetched (daily sync or the backfill
                     script) — kept out of cours_full/cours_response on
                     purpose so the main catalogue stays small; only
                     read back via GET /api/transcript/{video_id}, i.e.
                     when a visitor actually opens that video's
                     transcript panel.

Environment variables (set in Vercel or .env):
  YOUTUBE_API_KEY
  REDIS_URL        e.g. redis://default:xxx@xxx.upstash.io:6379
"""

import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()   # must run BEFORE importing playlist_videos_utils, which reads
                # YOUTUBE_API_KEY from os.environ at import time.

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis as aioredis
import ssl

from playlist_utils import get_raw_playlists, categorize_playlists, SKIPPED_PLAYLIST_IDS
from playlist_videos_utils import enrich_structured_playlists
from debug_logger import DebugLogger

# ── Config ────────────────────────────────────────────────────────────────────

# TARGET_URLS: checked on EVERY sync (incremental — only new videos).
TARGET_URLS = [
    "https://www.youtube.com/@Rabbi_Aharon_Butbul/playlists",
    "https://www.youtube.com/@%D7%94%D7%A8%D7%91%D7%90%D7%94%D7%A8%D7%95%D7%9F%D7%91%D7%95%D7%98%D7%91%D7%95%D7%9C-%D7%A97%D7%9E/playlists",
]

# FULL_SCAN_ONLY_URLS: the @nissimtrabelsy3957 channel tabs. This channel is
# a closed/old source that's skipped on normal incremental syncs to save API
# quota and sync time — but if Redis is empty (cold start / cache wiped),
# we still need to be able to rebuild the FULL catalogue from scratch, so
# these are added back in for that case only. See _build_response().
FULL_SCAN_ONLY_URLS = [
    "https://www.youtube.com/@nissimtrabelsy3957/streams",
    "https://www.youtube.com/@nissimtrabelsy3957/videos",
    "https://www.youtube.com/@nissimtrabelsy3957/playlists",
]


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
    # Explicit timeouts + one automatic retry: without these, a slow/flaky
    # link to Upstash (common on some networks/VPNs for non-443 ports)
    # hangs for redis-py's long internal default before raising a raw,
    # unhelpful TimeoutError deep in the traceback.
    return await aioredis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=10,
        socket_timeout=10,
        retry_on_timeout=True,
        health_check_interval=30,
    )


def _extract_keywords(all_videos: list[dict]) -> list[str]:
    """
    Collects every distinct AI-extracted topic keyword
    (video["topics"][*]["keyword"]) across all videos, deduplicated and
    sorted alphabetically. This is what powers the frontend's search
    keyword listbox — computing it here (once, server-side) means the
    frontend never has to walk the full video catalogue itself just to
    populate a suggestions list.
    """
    seen: set[str] = set()
    for v in all_videos:
        for t in (v.get("topics") or []):
            kw = (t.get("keyword") or "").strip()
            if kw:
                seen.add(kw)
    return sorted(seen)


async def _save_keywords_list(r, all_videos: list[dict]) -> list[str]:
    """Computes the distinct keyword list and persists it to Redis
    (no TTL — refreshed alongside cours_response). Returns the list."""
    keywords = _extract_keywords(all_videos)
    await r.set("keywords_list", json.dumps(keywords, ensure_ascii=False))
    return keywords


def _chunk_transcript_by_topics(topics: list, segments: list) -> list[dict]:
    """
    Splits the flat list of transcript segments into contiguous chunks
    aligned to the video's AI-extracted topic markers, so the stored
    transcript is already organized "by keyword" instead of being one
    long undifferentiated list.

    Given topics sorted by start time [t0, t1, ..., tN], produces:
      chunk 0   : [0, t0.start)          — keyword: None (intro, before
                                            the first topic starts; only
                                            included if non-empty)
      chunk 1   : [t0.start, t1.start)   — keyword: t0.keyword
      chunk 2   : [t1.start, t2.start)   — keyword: t1.keyword
      ...
      chunk N+1 : [tN.start, video end)  — keyword: tN.keyword

    Example — topics = [{"keyword": "A", "start": 7}, {"keyword": "B",
    "start": 60}] over a video that runs to e.g. 234s produces 3 chunks:
    [0-7) (intro), [7-60) keyword "A", [60-234) keyword "B".

    Each chunk is {"keyword": str | None, "start": float, "end": float,
    "text": str} where `text` is the join of every segment whose start
    falls in [start, end).
    """
    if not segments:
        return []

    sorted_topics = sorted(
        (t for t in (topics or []) if t.get("keyword")),
        key=lambda t: float(t.get("start", 0)),
    )

    video_end = max(s["start"] + s.get("duration", 0.0) for s in segments)

    if not sorted_topics:
        # No topics at all — fall back to one single untitled chunk
        # covering the whole transcript.
        text = " ".join(s["text"] for s in segments)
        return [{"keyword": None, "start": 0.0, "end": video_end, "text": text}]

    boundaries = [0.0] + [float(t["start"]) for t in sorted_topics] + [video_end]
    keywords = [None] + [t["keyword"] for t in sorted_topics]

    chunks = []
    for i in range(len(boundaries) - 1):
        start, end = boundaries[i], boundaries[i + 1]
        if start == end:
            # Empty intro chunk (first topic starts at 0s) — skip it.
            continue
        text = " ".join(s["text"] for s in segments if start <= s["start"] < end)
        chunks.append({"keyword": keywords[i], "start": start, "end": end, "text": text})
    return chunks


async def _save_transcript(r, video: dict, segments: list) -> None:
    """
    Persists one video's transcript to its own `transcript:<id>` Redis
    key (see module docstring) — kept separate from cours_full/
    cours_response so the main catalogue payload stays small. Only ever
    read back on demand via GET /api/transcript/{video_id}.

    Stores the transcript split into per-keyword chunks (see
    _chunk_transcript_by_topics) rather than the raw flat segment list,
    using this video's `topics` (already present in cours_full) as the
    chunk boundaries — so each chunk is exactly the transcript text for
    one AI-extracted topic, ready for the frontend to show when someone
    clicks that keyword.
    """
    vid_id = video.get("id")
    if not vid_id or not segments:
        return
    chunks = _chunk_transcript_by_topics(video.get("topics") or [], segments)
    payload = {
        "video_id": vid_id,
        "chunks": chunks,
        "updated": video.get("transcript_updated"),
    }
    await r.set(f"transcript:{vid_id}", json.dumps(payload, ensure_ascii=False))


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

    # 1b. Redis empty (cold start / cache wiped)? Fall back to a FULL scan:
    #     re-add the normally-skipped nissimtrabelsy3957 channel tabs and
    #     stop excluding the old/closed playlists, so we can rebuild the
    #     whole catalogue from scratch instead of missing content forever.
    is_full_scan = len(existing) == 0
    urls_to_scan = TARGET_URLS + FULL_SCAN_ONLY_URLS if is_full_scan else TARGET_URLS
    skip_ids = set() if is_full_scan else SKIPPED_PLAYLIST_IDS

    # 2. Discover playlists from the channel pages
    for url in urls_to_scan:
        print(f"[DEBUG] Processing TARGET_URL: {url}"
              + (" (full scan — nothing skipped)" if is_full_scan else ""))
    raw_playlists = get_raw_playlists(urls_to_scan, skip_ids=skip_ids)
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
    from playlist_videos_utils import extract_hebraic_year
    for v in all_videos:
        title = v.get("title", "")
        current_cat = v.get("category", "אחר")
        matches = find_matching_categories(title)
        if matches:
            correct_cat = matches[0][0]
            if correct_cat != current_cat:
                v["category"] = correct_cat

        # Backfill hebraic_year for videos stored before this field existed,
        # or re-derive it if it's missing/empty.
        if not v.get("hebraic_year"):
            v["hebraic_year"] = extract_hebraic_year(title) or extract_hebraic_year(v.get("playlist", ""))

    # 5b. Auto-attach Hebrew transcript + AI topic markers (keyword + start
    #     position) for newly-added הלכה יומית videos only. Existing videos
    #     that predate this feature are handled separately by
    #     backfill_halacha_transcripts.py, so this stays fast and can't
    #     make the daily sync run away on a big backfill.
    new_ids = fresh_ids - existing_ids
    if new_ids:
        from halacha_transcripts import HALACHA_CATEGORY, process_video_transcript
        from ai_keywords_utils import QuotaExhaustedError
        from transcript_utils import TranscriptFetchBlocked
        new_halacha_videos = [
            v for v in all_videos
            if v.get("id") in new_ids and v.get("category") == HALACHA_CATEGORY
        ]
        if new_halacha_videos:
            max_auto = int(os.environ.get("MAX_AUTO_TRANSCRIPTS", "5"))
            print(f"[transcript] {len(new_halacha_videos)} new {HALACHA_CATEGORY} video(s) "
                  f"this sync — processing up to {max_auto}")
            for v in new_halacha_videos[:max_auto]:
                try:
                    _ok, segments = process_video_transcript(v, logger=True)
                    if segments:
                        await _save_transcript(r, v, segments)
                except (QuotaExhaustedError, TranscriptFetchBlocked) as e:
                    print(f"[transcript] {e}\n[transcript] stopping early — "
                          f"remaining video(s) this sync would fail the same way.")
                    break
                except Exception as e:
                    print(f"[transcript] unexpected failure for {v.get('id')}: {e}")
            skipped = len(new_halacha_videos) - max_auto
            if skipped > 0:
                print(f"[transcript] {skipped} video(s) deferred — run "
                      f"backfill_halacha_transcripts.py to catch up.")

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
    # No TTL: this is only ever overwritten by the next daily sync.
    await r.set("cours_response", json.dumps(response_body))
    await _save_keywords_list(r, all_videos)

    logger.log_run_summary()
    log_content = logger.get_log_content()
    logger.close()

    await r.set("last_debug_log", log_content)

    return response_body


# ── Endpoints ─────────────────────────────────────────────────────────────────

async def _response_from_full(r, all_videos: list[dict]) -> dict:
    """
    Builds a response body straight from the permanent store (cours_full),
    with NO call to YouTube. This is only a safety net for the rare case
    where cours_response is missing (e.g. manually deleted, or a plan-
    level TTL on the Redis provider) while cours_full is still intact —
    it should almost never run in normal operation, since cours_response
    now has no TTL of its own.
    """
    catalogue: dict[str, list] = {}
    for v in all_videos:
        cat = v.get("category", "אחר")
        catalogue.setdefault(cat, []).append(v)

    for cat in catalogue:
        catalogue[cat].sort(
            key=lambda x: x.get("upload_date") or "",
            reverse=True,
        )

    last_sync = await r.get("last_sync_date")
    response_body = {
        "catalog": catalogue,
        "total": len(all_videos),
        "new": 0,
        "last_sync": last_sync,
    }

    # Re-cache it (no TTL) so this rebuild doesn't have to happen again
    # until the next real sync overwrites it.
    await r.set("cours_response", json.dumps(response_body))
    await _save_keywords_list(r, all_videos)

    return response_body


@app.get("/api/cours")
async def get_cours():
    """
    Main endpoint consumed by the React frontend.

    Stale-while-revalidate:
      - cours_response exists -> return it directly (this is the normal
        case: it has no TTL, so it's always there once a sync has run).
      - cours_response is missing (rare — see _response_from_full) but
        cours_full has data -> rebuild it straight from cours_full (no
        YouTube calls, no live sync). The catalogue itself is only ever
        refreshed for real by the Vercel cron job hitting POST /api/sync
        once a day at 6am — visitors never trigger a full sync.
      - cours_full is ALSO empty (true cold start, e.g. first deploy or
        a wiped Redis) -> nothing to serve at all, so we fall back to a
        real sync just this once so the site isn't blank.
    """
    try:
        r = await get_redis()
        try:
            cached = await r.get("cours_response")
            if cached:
                return json.loads(cached)

            full_raw = await r.get("cours_full")
            if full_raw:
                return await _response_from_full(r, json.loads(full_raw))

            # True cold start: no cached response AND no permanent store.
            # This is the only case where a request can trigger a live sync.
            return await _build_response(r)
        finally:
            await r.aclose()
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


@app.get("/api/keywords")
async def get_keywords():
    """
    Returns the distinct, sorted list of AI-extracted topic keywords for
    the frontend's search suggestions listbox: { "keywords": [...] }.

    Reads straight from the keywords_list Redis key (kept fresh by every
    sync / rebuild — see _save_keywords_list), so this is a cheap lookup
    with no YouTube calls and no need to walk the full catalogue. If it's
    somehow missing (e.g. very first deploy before any sync has run), it
    falls back to deriving it from cours_full and caching the result.
    """
    try:
        r = await get_redis()
        try:
            cached = await r.get("keywords_list")
            if cached:
                return {"keywords": json.loads(cached)}

            full_raw = await r.get("cours_full")
            all_videos = json.loads(full_raw) if full_raw else []
            keywords = await _save_keywords_list(r, all_videos)
            return {"keywords": keywords}
        finally:
            await r.aclose()
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


@app.get("/api/transcript/{video_id}")
async def get_transcript(video_id: str):
    """
    Returns the Hebrew transcript for one video, pre-split into one
    chunk per AI-extracted topic keyword, read straight from its own
    `transcript:<video_id>` Redis key — no scanning of cours_full/
    cours_response required.

    Meant to be called on demand only: when a visitor opens a video and
    clicks the "show transcript" button (or clicks a specific topic
    keyword). Each returned chunk's `keyword` matches one of this
    video's `topics[*].keyword` from /api/cours, so the frontend can
    match a clicked keyword to its chunk directly and just display
    `chunk["text"]` — no client-side searching through raw segments
    needed. The intro before the first topic (if any) is included as a
    chunk with `keyword: null`.

    Response shape:
      { "video_id": str,
        "chunks": [{"keyword": str | None, "start": float,
                     "end": float, "text": str}, ...],
        "updated": str | None }

    404 if this video has no transcript stored yet (never processed, or
    it genuinely has no Hebrew captions — check /api/cours for that
    video's `transcript_status` to tell the two apart).
    """
    try:
        r = await get_redis()
        try:
            raw = await r.get(f"transcript:{video_id}")
            if not raw:
                raise HTTPException(status_code=404, detail="No transcript available for this video")
            return json.loads(raw)
        finally:
            await r.aclose()
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


@app.post("/api/sync")
@app.get("/api/sync")
async def force_sync(authorization: str | None = Header(default=None)):
    """
    Called by the Vercel cron job once a day, or by a YouTube PubSubHubbub
    webhook when a new video is published.
    Runs the real incremental sync against YouTube and overwrites
    cours_full / cours_response with fresh data.

    NOTE: Vercel Cron Jobs only ever send GET requests to the configured
    path — they cannot be made to send POST. That's why this route accepts
    both. If a CRON_SECRET env var is set (Vercel Project Settings →
    Environment Variables), Vercel automatically attaches it as
    "Authorization: Bearer <CRON_SECRET>" on cron-triggered requests, and
    we verify it here so nobody else can trigger a sync by just hitting
    this URL in a browser.
    """
    secret = os.environ.get("CRON_SECRET")
    if secret and authorization != f"Bearer {secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    r = await get_redis()
    try:
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
            return {
                "cache_active": bool(has_cache),
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
    from playlist_videos_utils import fetch_videos_for_playlist, fetch_videos_by_ids

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
            is_full_scan = len(existing) == 0
            urls_to_scan = TARGET_URLS + FULL_SCAN_ONLY_URLS if is_full_scan else TARGET_URLS
            skip_ids = set() if is_full_scan else SKIPPED_PLAYLIST_IDS
            if is_full_scan:
                log("  cours_full is empty -> FULL SCAN (nissimtrabelsy3957 tabs + all playlists included)")
            try:
                for url in urls_to_scan:
                    log(f"  Processing TARGET_URL: {url}")
                raw_playlists = get_raw_playlists(urls_to_scan, skip_ids=skip_ids)
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

                real_playlists = [p for p in playlists if p.get("kind") != "video"]
                loose_videos   = [p for p in playlists if p.get("kind") == "video"]

                for pl in real_playlists:
                    pl_url   = pl.get("url", "")
                    pl_title = pl.get("title", "")
                    log(f"\n  [{category}] {pl_title}")
                    try:
                        new_vids, mismatched = fetch_videos_for_playlist(
                            pl_url, existing_ids,
                            category=category,
                            playlist_title=pl_title,
                            logger=None,
                            required_keyword=pl.get("required_keyword"),
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

                if loose_videos:
                    label = f"{category} (direct videos)"
                    log(f"\n  [{category}] {label} — {len(loose_videos)} candidate video(s)")
                    try:
                        new_vids, mismatched = fetch_videos_by_ids(
                            loose_videos, existing_ids,
                            category=category,
                            source_label=label,
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

