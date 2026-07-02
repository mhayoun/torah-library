"""
ai_keywords_utils.py
---------------------
Uses the Google Gemini API (free tier) to read a Hebrew הלכה יומית
transcript (with per-segment timestamps) and extract the distinct
halachic subjects discussed, each anchored to a start-time position in
seconds — this is what lets the frontend jump straight to that part of
the video.

Requires GEMINI_API_KEY to be set in the environment (.env). Get a free
key (no credit card required) at https://aistudio.google.com/apikey —
current free-tier quotas are listed at https://ai.google.dev/gemini-api/docs/pricing
and can change, so it's worth a quick check there if you start seeing
429 rate-limit errors.

Uses the current Google GenAI SDK (`google-genai` package, `from google
import genai`) — the older `google-generativeai` package is deprecated.
"""

import os
import json
import re

from google import genai

# Override with e.g. GEMINI_MODEL=gemini-2.5-flash-lite in .env for higher
# free-tier request-per-day headroom at slightly lower quality.
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# הלכה יומית videos are short (a few minutes), so this is a generous cap
# that should essentially never be hit — it just protects against an
# unexpectedly long transcript blowing up the request.
MAX_TRANSCRIPT_CHARS = 20000

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=api_key)
    return _client


def _build_timestamped_transcript(segments):
    """Formats segments as '[12s] text' lines so the model can anchor
    each topic it identifies to an actual timestamp from the transcript."""
    lines = []
    total_chars = 0
    for seg in segments:
        line = f"[{int(seg['start'])}s] {seg['text']}"
        total_chars += len(line)
        if total_chars > MAX_TRANSCRIPT_CHARS:
            break
        lines.append(line)
    return "\n".join(lines)


_SYSTEM_PROMPT = """אתה מנתח תמלול של שיעור "הלכה יומית" בעברית, עם חותמות זמן.
המטרה שלך: לזהות את הנושאים ההלכתיים המרכזיים והנפרדים שנדונים בשיעור, לפי סדר הופעתם.

עבור כל נושא, ציין:
- "keyword": ביטוי קצר וברור בעברית (2-6 מילים) שמסכם את הנושא ההלכתי.
- "start": זמן ההתחלה בשניות (מספר שלם), שבו מתחיל הדיון בנושא, כפי שמופיע בפועל באחת מחותמות הזמן שסופקו.

הנחיות:
- החזר בין נושא אחד לשמונה נושאים, בהתאם לאורך השיעור ולמגוון התכנים.
- אל תפצל נושא רציף אחד למספר נושאים קטנים; מזג קטעים סמוכים ששייכים לאותו נושא.
- ה-"start" חייב להתאים לאחת מחותמות הזמן שסופקו בפועל (או להיות קרוב מאוד אליה).
- החזר אך ורק JSON תקין, ללא markdown, וללא כל טקסט נוסף מחוץ ל-JSON, בפורמט הבא בדיוק:
{"topics": [{"keyword": "...", "start": 0}, ...]}
"""


def extract_topics(title: str, segments: list) -> list:
    """
    Calls Gemini to extract {keyword, start} topic markers from a Hebrew
    transcript. Returns a list of dicts, sorted by start time ascending:
      [{"keyword": str, "start": float}, ...]
    Returns [] if segments is empty or the model output can't be parsed.
    """
    if not segments:
        return []

    transcript_block = _build_timestamped_transcript(segments)
    last = segments[-1]
    video_duration = last["start"] + last.get("duration", 0)

    user_content = (
        f"כותרת השיעור: {title}\n\n"
        f"אורך השיעור בקירוב: {int(video_duration)} שניות\n\n"
        f"תמלול עם חותמות זמן:\n{transcript_block}"
    )

    client = _get_client()
    response = client.models.generate_content(
        model=MODEL,
        contents=user_content,
        config={
            "system_instruction": _SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "temperature": 0.2,
        },
    )

    raw_text = (response.text or "").strip()

    # Defensive cleanup in case the model wraps the JSON in a code fence
    # despite response_mime_type=application/json.
    raw_text = re.sub(r"^```(json)?", "", raw_text).strip()
    raw_text = re.sub(r"```$", "", raw_text).strip()

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return []

    raw_topics = parsed.get("topics", [])
    cleaned = []
    seen_starts = set()
    for t in raw_topics:
        keyword = str(t.get("keyword", "")).strip()
        if not keyword:
            continue
        try:
            start = float(t.get("start", 0))
        except (TypeError, ValueError):
            continue
        start = max(0.0, min(start, video_duration))
        rounded = round(start)
        if rounded in seen_starts:
            continue  # collapse near-duplicate positions
        seen_starts.add(rounded)
        cleaned.append({"keyword": keyword, "start": start})

    cleaned.sort(key=lambda x: x["start"])
    return cleaned
