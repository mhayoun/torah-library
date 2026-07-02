"""
transcript_utils.py
--------------------
Fetches the Hebrew transcript (subtitles/captions) for a YouTube video
using the `youtube-transcript-api` library. This is the source used to
pull the Hebrew text that later gets fed to Claude for topic/keyword
extraction (see ai_keywords_utils.py).

Why youtube-transcript-api (over yt-dlp, which is already a dependency
here for playlist scraping): it returns per-segment timed text directly
(text + start + duration) without needing to download/parse a subtitle
file, which is exactly the shape we need to anchor AI-extracted topics
to a "skip to this second" position.
"""

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

# YouTube has historically used 'iw' (old ISO 639-1 code for Hebrew) for
# auto-generated captions, and 'he' for manually-uploaded ones. Try both,
# with regional variants as a fallback.
HEBREW_LANG_CODES = ["iw", "he", "iw-IL", "he-IL"]


class NoHebrewTranscript(Exception):
    """Raised when no Hebrew transcript/caption track could be found or
    derived (manual, auto-generated, or translated) for a given video."""


def _normalize(raw_segments):
    """Normalizes whatever the library returned into a plain list of
    {"text": str, "start": float, "duration": float} dicts."""
    segments = []
    for seg in raw_segments:
        if isinstance(seg, dict):
            text = seg.get("text", "")
            start = seg.get("start", 0.0)
            duration = seg.get("duration", 0.0)
        else:
            # Newer versions of youtube-transcript-api return
            # FetchedTranscriptSnippet objects instead of dicts.
            text = getattr(seg, "text", "")
            start = getattr(seg, "start", 0.0)
            duration = getattr(seg, "duration", 0.0)
        text = (text or "").strip()
        if not text:
            continue
        segments.append({
            "text": text,
            "start": float(start or 0.0),
            "duration": float(duration or 0.0),
        })
    return segments


def _fetch_via_transcript_list(video_id):
    """
    Fallback path used when the direct shortcut isn't available/fails:
    enumerate all transcript tracks for the video and pick the best
    Hebrew match — manually created first, then auto-generated, then
    (last resort) any track machine-translated into Hebrew.
    """
    transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

    try:
        t = transcript_list.find_manually_created_transcript(HEBREW_LANG_CODES)
        return t.fetch()
    except NoTranscriptFound:
        pass

    try:
        t = transcript_list.find_generated_transcript(HEBREW_LANG_CODES)
        return t.fetch()
    except NoTranscriptFound:
        pass

    for t in transcript_list:
        if getattr(t, "is_translatable", False):
            try:
                return t.translate("iw").fetch()
            except Exception:
                continue

    raise NoHebrewTranscript(
        f"No Hebrew transcript/caption available for video {video_id}"
    )


def fetch_hebrew_transcript(video_id: str):
    """
    Returns (segments, full_text):
      segments  : list of {"text": str, "start": float, "duration": float},
                  ordered by start time — this is what gets timestamp-
                  annotated and sent to Claude.
      full_text : the full Hebrew transcript as a single joined string —
                  this is what gets stored on the video object.

    Raises NoHebrewTranscript if this video has no Hebrew captions at all
    (disabled, unavailable, or genuinely no Hebrew track/translation).
    """
    raw = None

    # Fast path: works on the widely-deployed <1.0 versions of the library.
    try:
        raw = YouTubeTranscriptApi.get_transcript(video_id, languages=HEBREW_LANG_CODES)
    except AttributeError:
        # 1.x releases replaced the classmethod with an instance API.
        try:
            api = YouTubeTranscriptApi()
            raw = api.fetch(video_id, languages=HEBREW_LANG_CODES)
        except Exception:
            raw = None
    except NoTranscriptFound:
        raw = None
    except TranscriptsDisabled:
        raise NoHebrewTranscript(f"Captions are disabled for video {video_id}")
    except VideoUnavailable:
        raise NoHebrewTranscript(f"Video {video_id} is unavailable")

    if raw is None:
        try:
            raw = _fetch_via_transcript_list(video_id)
        except NoHebrewTranscript:
            raise
        except TranscriptsDisabled:
            raise NoHebrewTranscript(f"Captions are disabled for video {video_id}")
        except VideoUnavailable:
            raise NoHebrewTranscript(f"Video {video_id} is unavailable")
        except Exception as e:
            raise NoHebrewTranscript(f"Failed to fetch transcript for {video_id}: {e}")

    segments = _normalize(raw)
    if not segments:
        raise NoHebrewTranscript(f"Empty transcript for video {video_id}")

    full_text = " ".join(s["text"] for s in segments)
    return segments, full_text
