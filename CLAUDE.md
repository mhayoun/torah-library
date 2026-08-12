# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Torah lecture library (Hebrew) for הרב אהרון בוטבול: a Python/FastAPI backend that scrapes YouTube playlists/videos, categorizes them, and — for the "הלכה יומית" (daily halacha) category — fetches Hebrew transcripts and uses an LLM to extract topic markers; a React + Vite frontend renders the catalogue. Both halves deploy to Vercel as **separate projects** (`backend/` and `frontend/` each have their own `vercel.json` and `.vercel/`).

**Important:** `README.md` and `.github/workflows/update-videos.yml` describe an older architecture (backend writes a static `categorized_videos.json` file, no Redis/FastAPI). That pipeline is legacy/no longer the primary path — the live architecture is the Redis-backed FastAPI backend described below (`backend/main.py`'s docstring is the authoritative reference). Don't assume the README is current.

## Commands

### Backend (`backend/`)
```bash
source venv/bin/activate            # or .venv at repo root
pip install -r requirements.txt

uvicorn main:app --reload --port 8000     # run API locally
curl -X POST http://localhost:8000/api/sync   # trigger a local sync

python debug_sync.py --verbose      # dry run: discovery + playlist walk, NO Redis writes
curl http://localhost:8000/api/debug-sync     # same dry-run report, via the deployed API

python backfill_halacha_transcripts.py --limit 1   # backfill transcripts/topics for existing videos missing them
python util_purge_private_videos.py            # dry run
python util_purge_private_videos.py --apply     # actually delete purged videos from Redis

./util_clean_redis.sh               # wipe Redis cache keys (see util_clean_redis.sh for exact keys)
```
There is no automated test suite for the backend — validate changes via `debug_sync.py` (read-only) and by hitting `/api/debug-sync` / `/api/status` against a running instance.

### Frontend (`frontend/`)
```bash
npm install
npm run dev       # http://localhost:5173
npm run build     # -> dist/
npm run preview
```
No lint/test scripts are configured in `package.json`.

### Deploys
- Backend and frontend are independent Vercel projects. Backend auto-deploys via `.github/workflows/deploy-backend.yml` (triggers a Vercel deploy hook on push to `master` touching `backend/**`).
- Frontend's `vercel.json` rewrites `/api/:path*` to the backend's Vercel URL — so in production the frontend calls its *own* domain's `/api/*`, which Vercel rewrites cross-project to the backend.
- A Vercel Cron (`backend/vercel.json`, `crons`) hits `GET /api/sync` once daily — this is the **only** regular data refresh in production. Cron requests carry `Authorization: Bearer $CRON_SECRET` automatically when `CRON_SECRET` is set as a backend env var.

## Architecture

### Data flow
1. **Discovery** (`playlist_utils.py`): `yt-dlp` scrapes playlists (and, for a couple of channel tabs, individual videos) from the two Rav Butbul YouTube channels. Titles are matched against `CATEGORY_MAPPING` keywords to bucket each playlist/video into a category (הלכה יומית, השיעור השבועי, שיחת חולין, דעת ותורה, הליכות עולם, or אחר). `SKIPPED_PLAYLIST_IDS` are old/closed playlists normally excluded from every sync to save quota.
2. **Enrichment** (`playlist_videos_utils.py`): calls the YouTube Data API v3 to fetch per-video metadata. **Incremental by design** — given the set of already-known video IDs, it stops paginating a playlist as soon as it hits a known ID. Also derives `hebraic_year` from Hebrew titles (fully dynamic gematria-based parsing, no hardcoded year list).
3. **Transcripts + AI topics** (`transcript_utils.py` + `ai_keywords_utils.py` + `halacha_transcripts.py`), **הלכה יומית only**: `youtube-transcript-api` fetches the Hebrew transcript (timed segments); `ai_keywords_utils.extract_topics` sends it to an LLM to extract distinct halachic subjects, each anchored to a start-time offset. Primary provider is **Gemini** (`GEMINI_API_KEY`), with automatic fallback to **Groq** (`GROQ_API_KEY`) once every Gemini model candidate hits a 429. Neither provider is hardcoded to one model by default — available models are discovered and ranked, retried on quota errors (see `GEMINI_MODEL` / `GROQ_MODEL` env vars to pin one). New videos get this automatically during the daily sync (capped by `MAX_AUTO_TRANSCRIPTS` so a burst of uploads can't blow the Vercel function timeout); `backfill_halacha_transcripts.py` catches up any older videos deferred that way.
4. **Orchestration + storage** (`main.py`, `_build_response`): merges freshly-fetched videos with the existing catalogue, re-applies category/title corrections to *all* videos (so past mistakes get fixed retroactively), rebuilds the category→videos catalogue, and persists it to Redis.

### Redis is the source of truth (not the `categorized_videos.json` file)
Keys (see the full docstring at the top of `backend/main.py` for exact semantics):
- `cours_full` — permanent flat list of every video object, no TTL.
- `cours_response` — the full `/api/cours` response body (`{catalog, total, new, last_sync}`), no TTL, only overwritten by a sync.
- `last_sync_date`, `last_debug_log`.
- `keywords_list` — sorted distinct list of all AI-extracted topic keywords, powering the frontend's search suggestions without it having to scan the whole catalogue.
- `transcript:<video_id>` — one key per video with a transcript, pre-chunked by topic boundary (see `_chunk_transcript_by_topics`) so the frontend can jump straight to the text for a clicked keyword. Deliberately kept out of `cours_full`/`cours_response` to keep the main catalogue payload small; only read on demand via `GET /api/transcript/{video_id}`.

`GET /api/cours` is stale-while-revalidate but visitors **never** trigger a live YouTube sync except on a true cold start (Redis wiped and empty) — the only path that pays YouTube API cost is the daily cron hitting `POST/GET /api/sync`.

### Frontend
- `useVideos.js` / `useKeywords.js` are the only data-fetching hooks — each hits its API endpoint once, caches the result in `sessionStorage` (6h TTL matching the backend's own freshness assumption), and hydrates from that cache on remount. There's no client-side data-fetching library.
- `App.jsx` holds the top-level tab state (`activeTab`) and is a plain string switch between "כל הקטגוריות" (Home), a specific category name, or the sentinel `'__search__'` — no router.
- All Hebrew Right-to-left; category names *are* the tab identifiers used throughout (not slugs) — matching against `CATEGORY_MAPPING` keys in `playlist_utils.py` is exact-string.

### Debugging a sync gone wrong
`main.py`'s `/api/debug-sync` (or the local `debug_sync.py`) runs the full discovery + fetch pipeline read-only and prints a step-by-step report (Redis state → playlist discovery → per-playlist fetch → merge summary) — this is the fastest way to diagnose "why aren't new videos showing up" (quota exhaustion vs. Vercel timeout vs. actually nothing new) without risking a bad write to the permanent store.
