"""
halacha_transcripts.py
-----------------------
Shared logic to fetch a video's Hebrew transcript (used transiently, not
stored) and attach AI-extracted topic markers (keyword + start position
in seconds) to a single הלכה יומית video object. Used by both:

  - backfill_halacha_transcripts.py — one-off manual backfill for
    existing videos in cours_full that don't have a transcript yet.
  - main.py's daily sync (_build_response) — automatic, new videos only,
    capped by MAX_AUTO_TRANSCRIPTS so it can't blow the Vercel timeout.

Fields written onto the video dict (the raw transcript text itself is
NOT kept — only the derived topic markers, to keep cours_full/cours_response
small):
  topics               — [{"keyword": str, "start": float}, ...]
  transcript_status    — "done" | "no_captions" | "error"
  transcript_error     — present only when status is "no_captions"/"error"
  transcript_updated   — ISO timestamp of the last processing attempt
"""

from datetime import datetime, timezone

from transcript_utils import fetch_hebrew_transcript, NoHebrewTranscript
from ai_keywords_utils import extract_topics, QuotaExhaustedError

HALACHA_CATEGORY = "הלכה יומית"


def needs_transcript(video: dict) -> bool:
    """
    True if this video hasn't been successfully processed (or definitively
    marked as having no captions) yet, and should be picked up by the
    backfill script or the daily sync.
    """
    return video.get("transcript_status") not in ("done", "no_captions")


def process_video_transcript(video: dict, logger=None) -> bool:
    """
    Mutates `video` in place. Returns True if topics were successfully
    extracted, False otherwise (no captions available, or an error at
    either the transcript-fetch or AI-extraction step).
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
        return False
    except Exception as e:
        video["transcript_status"] = "error"
        video["transcript_error"] = str(e)
        video["transcript_updated"] = now()
        if logger:
            print(f"   ❌ Transcript fetch failed for '{title}' ({vid_id}): {e}")
        return False

    try:
        topics = extract_topics(title, segments)
    except QuotaExhaustedError:
        # Account/project-level condition, not this video's fault — don't
        # write a misleading transcript_error onto it. Let the caller
        # (backfill script / daily sync) decide to stop the batch.
        raise
    except Exception as e:
        video["topics"] = []
        video["transcript_status"] = "error"
        video["transcript_error"] = f"AI extraction failed: {e}"
        video["transcript_updated"] = now()
        if logger:
            print(f"   ❌ Keyword extraction failed for '{title}' ({vid_id}): {e}")
        return False

    video["topics"] = topics
    video["transcript_status"] = "done"
    video.pop("transcript_error", None)
    video["transcript_updated"] = now()
    if logger:
        print(f"   ✅ {len(topics)} topic(s) extracted for '{title}' ({vid_id})")
    return True
