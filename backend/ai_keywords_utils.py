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

# GEMINI_MODEL in .env always wins if set (e.g. GEMINI_MODEL=gemini-2.5-flash-lite
# for higher free-tier request-per-day headroom at slightly lower quality).
# Otherwise we ask the API which models are currently available for this key
# and pick one automatically — this avoids hardcoding a specific model name
# that Google can rename/retire later (which would otherwise fail every
# extraction with a 404 until someone notices and updates the constant).
_MODEL_OVERRIDE = os.environ.get("GEMINI_MODEL")
_discovered_model = None


class QuotaExhaustedError(RuntimeError):
    """
    Raised when Gemini returns 429 RESOURCE_EXHAUSTED. This is an
    account/project-level condition (free-tier quota set to 0, billing
    not linked, or a genuine rate limit) — NOT a problem with any
    particular video's transcript. Callers should stop processing
    further videos in the current run rather than retrying each one
    (they'll all fail identically) and should NOT record this as a
    per-video "error", since that would misleadingly suggest something
    is wrong with that specific video.
    """
    pass

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


def _pick_best_model(candidates: list) -> str:
    """
    Heuristic ranking, best first:
      1. Stable releases over preview/experimental ones (less likely to be
         pulled without notice).
      2. "flash" family over "pro" (fast + generous free-tier quota — this
         workload doesn't need pro-level reasoning).
      3. Plain flash over "-lite" (better quality; lite is still a fine
         fallback if that's all that's available).
      4. Newer version numbers first.
    """
    def rank(name: str):
        is_unstable = ("preview" in name) or ("exp" in name)
        is_pro = "pro" in name and "flash" not in name
        is_lite = "lite" in name
        return (is_unstable, is_pro, is_lite, name)

    return sorted(candidates, key=rank)[0]


def _discover_model() -> str:
    """
    Lists models available to this API key that support generateContent,
    and picks one via _pick_best_model. Result is cached for the life of
    the process. Falls back to a hardcoded default only if listing itself
    fails (e.g. transient network error) so the pipeline degrades gracefully
    instead of hard-failing.
    """
    global _discovered_model
    if _MODEL_OVERRIDE:
        print(f"[ai_keywords_utils] GEMINI_MODEL override in .env: using '{_MODEL_OVERRIDE}' "
              f"(skipping auto-discovery)")
        return _MODEL_OVERRIDE
    if _discovered_model:
        print(f"[ai_keywords_utils] Using cached model choice: {_discovered_model}")
        return _discovered_model

    client = _get_client()
    candidates = []
    try:
        print("[ai_keywords_utils] Listing Gemini models available for this API key…")
        for m in client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            supported = "generateContent" in actions
            name = m.name
            if name.startswith("models/"):
                name = name[len("models/"):]
            print(f"[ai_keywords_utils]   - {name}"
                  f"{'  ✅ generateContent' if supported else '  (no generateContent)'}")
            if supported:
                candidates.append(name)
    except Exception as e:
        print(f"[ai_keywords_utils] ❌ Could not list Gemini models ({type(e).__name__}: {e}); "
              f"falling back to gemini-2.5-flash")
        _discovered_model = "gemini-2.5-flash"
        return _discovered_model

    if not candidates:
        print("[ai_keywords_utils] ❌ No models support generateContent for this "
              "API key; falling back to gemini-2.5-flash")
        _discovered_model = "gemini-2.5-flash"
        return _discovered_model

    _discovered_model = _pick_best_model(candidates)
    print(f"[ai_keywords_utils] ✅ Auto-selected Gemini model: {_discovered_model} "
          f"(out of {len(candidates)} candidate(s))")
    return _discovered_model


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
    try:
        response = client.models.generate_content(
            model=_discover_model(),
            contents=user_content,
            config={
                "system_instruction": _SYSTEM_PROMPT,
                "response_mime_type": "application/json",
                "temperature": 0.2,
            },
        )
    except Exception as e:
        code = getattr(e, "code", None)
        text = str(e)
        if code == 429 or "RESOURCE_EXHAUSTED" in text or "429" in text[:20]:
            raise QuotaExhaustedError(
                "Gemini API quota exhausted (429 RESOURCE_EXHAUSTED). If the "
                "error mentions 'free_tier_requests, limit: 0', that means "
                "this API key's project has no free-tier quota granted at "
                "all — retrying won't help. Check your plan/billing at "
                "https://aistudio.google.com/apikey and current usage at "
                "https://ai.dev/rate-limit; linking a billing account "
                "usually unlocks quota within minutes. If it's a genuine "
                "rate limit instead (a nonzero limit you've temporarily "
                "used up), just wait and re-run."
            ) from e
        raise

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
