"""
halacha_transcripts.py
-----------------------
Shared logic to fetch a video's Hebrew transcript and attach AI-extracted
topic markers (keyword + start position in seconds) to a single הלכה
יומית video object. Used by both:

  - backfill_halacha_transcripts.py — one-off manual backfill for
    existing videos in cours_full that don't have a transcript yet.
  - main.py's daily sync (_build_response) — automatic, new videos only,
    capped by MAX_AUTO_TRANSCRIPTS so it can't blow the Vercel timeout.

Fields written onto the video dict (the raw transcript segments are NOT
kept here — only the derived topic markers, to keep cours_full/
cours_response small and fast to load on every page view):
  topics               — [{"keyword": str, "start": float}, ...]
  transcript_status    — "done" | "no_captions" | "error"
  transcript_error     — present only when status is "no_captions"/"error"
  transcript_updated   — ISO timestamp of the last processing attempt

The full transcript (per-segment text + timing) is instead handed back
to the caller as `segments`, which is responsible for persisting it
separately (see main.py's `transcript:<video_id>` Redis key / the
GET /api/transcript/<video_id> endpoint) so it's only ever loaded on
demand — when someone actually opens the transcript panel for a video —
rather than on every /api/cours page load.
"""

from datetime import datetime, timezone

from transcript_utils import fetch_hebrew_transcript, NoHebrewTranscript, TranscriptFetchBlocked
from ai_keywords_utils import extract_topics, QuotaExhaustedError, GeminiUnavailableError

HALACHA_CATEGORY = "הלכה יומית"


def needs_transcript(video: dict) -> bool:
    """
    True if this video hasn't been successfully processed (or definitively
    marked as having no captions) yet, and should be picked up by the
    backfill script or the daily sync.
    """
    return video.get("transcript_status") not in ("done", "no_captions")


def process_video_transcript(video: dict, logger=None, provider: str = "gemini") -> tuple[bool, list | None]:
    """
    Mutates `video` in place with the lightweight topic-marker fields
    (see module docstring). Returns (ok, segments):
      ok       — True if topics were successfully extracted, False
                 otherwise (no captions available, or an error at either
                 the transcript-fetch or AI-extraction step).
      segments — the full list of {"text", "start", "duration"} dicts
                 fetched for this video, or None if the fetch itself
                 failed. The caller is responsible for persisting this
                 (e.g. to the `transcript:<video_id>` Redis key) — it is
                 NOT written onto `video` / cours_full.
      provider — which AI provider to try first for topic extraction:
                 "gemini" (default) or "groq". Whichever one isn't tried
                 first is still used as an automatic fallback if the
                 first one fails — see extract_topics() in
                 ai_keywords_utils.py.
    """
    vid_id = video.get("id")
    title = video.get("title", "")
    now = lambda: datetime.now(timezone.utc).isoformat()

    try:
        segments, _full_text = fetch_hebrew_transcript(vid_id)
    except NoHebrewTranscript as e:
        video["transcript_status"] = "no_captions"
        video["transcript_error"] = str(e)
        video["transcript_updated"] = now()
        if logger:
            print(f"   ⚠️  No Hebrew captions for '{title}' ({vid_id}): {e}")
        return False, None
    except TranscriptFetchBlocked:
        # IP-level block, not this video's fault — don't write a
        # misleading transcript_error onto it, and definitely don't mark
        # it "no_captions" (it may well have captions; we just couldn't
        # reach YouTube right now). Let the caller decide to stop the batch.
        raise
    except Exception as e:
        video["transcript_status"] = "error"
        video["transcript_error"] = str(e)
        video["transcript_updated"] = now()
        if logger:
            print(f"   ❌ Transcript fetch failed for '{title}' ({vid_id}): {e}")
        return False, None

    try:
        topics = extract_topics(title, segments, provider=provider)
    except GeminiUnavailableError:
        # Either a real quota problem (QuotaExhaustedError) or a transient
        # server-side hiccup (GeminiTransientError) — neither is this
        # video's fault, so don't write a misleading transcript_error onto
        # it. `raise` (bare) re-raises the original specific subclass
        # unchanged, so the caller can tell the two apart and decide:
        # stop the whole batch (quota) vs. just skip this one and retry
        # later (transient).
        raise
    except Exception as e:
        video["topics"] = []
        video["transcript_status"] = "error"
        video["transcript_error"] = f"AI extraction failed: {e}"
        video["transcript_updated"] = now()
        if logger:
            print(f"   ❌ Keyword extraction failed for '{title}' ({vid_id}): {e}")
        # The transcript fetch itself succeeded even though AI extraction
        # didn't — still hand segments back so the transcript panel works
        # even for videos where topic extraction failed.
        return False, segments

    video["topics"] = topics
    video["transcript_status"] = "done"
    video.pop("transcript_error", None)
    video["transcript_updated"] = now()
    if logger:
        print(f"   ✅ {len(topics)} topic(s) extracted for '{title}' ({vid_id})")
    return True, segments
