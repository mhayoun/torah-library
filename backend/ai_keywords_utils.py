"""
ai_keywords_utils.py
---------------------
Uses an LLM to read a Hebrew הלכה יומית transcript (with per-segment
timestamps) and extract the distinct halachic subjects discussed, each
anchored to a start-time position in seconds — this is what lets the
frontend jump straight to that part of the video.

Primary provider: Google Gemini (free tier). Requires GEMINI_API_KEY in
the environment (.env). Get a free key (no credit card required) at
https://aistudio.google.com/apikey — current free-tier quotas are listed
at https://ai.google.dev/gemini-api/docs/pricing and can change, so it's
worth a quick check there if you start seeing 429 rate-limit errors.
Uses the current Google GenAI SDK (`google-genai` package, `from google
import genai`) — the older `google-generativeai` package is deprecated.

Before giving up on Gemini: if GEMINI_MODEL isn't pinned in .env, every
model available to this API key is tried in ranked order (best first)
when the current one hits a 429 — free-tier quotas are generally
per-model-per-day, not shared project-wide, so one exhausted model
doesn't necessarily mean they all are.

Fallback provider: Groq (optional). Only once *every* Gemini model
candidate has 429'd (see QuotaExhaustedError) AND GROQ_API_KEY is set in
the environment, extract_topics() automatically retries the same request
on Groq instead of failing the video. Get a free key at
https://console.groq.com/keys. Override the model with GROQ_MODEL in
.env (default: llama-3.3-70b-versatile). If GROQ_API_KEY isn't set, the
original Gemini QuotaExhaustedError is raised as before — Groq is purely
an optional safety net, not a replacement.
"""

import os
import json
import re

from google import genai

try:
    from groq import Groq
except ImportError:  # groq is an optional dependency — only needed if
    Groq = None       # GROQ_API_KEY is actually configured as a fallback.

# GEMINI_MODEL in .env always wins if set (e.g. GEMINI_MODEL=gemini-2.5-flash-lite
# for higher free-tier request-per-day headroom at slightly lower quality).
# Otherwise we ask the API which models are currently available for this key
# and pick one automatically — this avoids hardcoding a specific model name
# that Google can rename/retire later (which would otherwise fail every
# extraction with a 404 until someone notices and updates the constant).
_MODEL_OVERRIDE = os.environ.get("GEMINI_MODEL")
_discovered_models = None  # ranked list of ALL usable candidates, cached once
_exhausted_models = set()  # models that hit 429 this run — skipped on retry,
                            # since a model's daily quota won't refill mid-run

# Groq is only used as a fallback when Gemini's quota is exhausted, so
# there's no auto-discovery dance — just a sane, fast, JSON-mode-capable
# default that can be overridden.
_GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


class QuotaExhaustedError(RuntimeError):
    """
    Raised when every Gemini model candidate has failed with a retryable
    error (429 RESOURCE_EXHAUSTED, or a transient 500/503 server-side
    error) and no working fallback (Groq) was available either.

    Despite the name, this now also covers transient "model overloaded"
    5xx errors, not just quota. Either way it's not a problem with any
    particular video's transcript — callers should stop processing
    further videos in the current run rather than retrying each one
    (they'll all fail identically against the same exhausted/overloaded
    models) and should NOT record this as a per-video "error", since that
    would misleadingly suggest something is wrong with that specific video.
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


_groq_client = None


def _get_groq_client():
    """
    Returns a Groq client, or None if GROQ_API_KEY isn't set / the groq
    package isn't installed — callers treat None as "no fallback
    available" rather than raising, since Groq is optional.
    """
    global _groq_client
    if _groq_client is not None:
        return _groq_client
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key or Groq is None:
        return None
    _groq_client = Groq(api_key=api_key)
    return _groq_client


# Models known to permanently reject a request shape this pipeline always
# sends (system_instruction + JSON mime type) — filtered out at discovery
# time so we never waste an API call (and a full round-trip's worth of
# sleep-before-next-video delay) finding this out per-run. Confirmed via
# a 400 INVALID_ARGUMENT: "Developer instruction is not enabled for
# models/antigravity-preview-05-2026". If GEMINI_MODEL explicitly pins one
# of these, that explicit choice is still respected — this list only
# trims the auto-discovered candidate pool.
_KNOWN_INCOMPATIBLE_MODELS = {
    "antigravity-preview-05-2026",
}


def _rank_model(name: str):
    """
    Heuristic ranking key, best first:
      1. Stable releases over preview/experimental ones (less likely to be
         pulled without notice).
      2. "flash" family over "pro" (fast + generous free-tier quota — this
         workload doesn't need pro-level reasoning).
      3. Plain flash over "-lite" (better quality; lite is still a fine
         fallback if that's all that's available).
      4. Newer version numbers first.
    """
    is_unstable = ("preview" in name) or ("exp" in name)
    is_pro = "pro" in name and "flash" not in name
    is_lite = "lite" in name
    return (is_unstable, is_pro, is_lite, name)


def _get_model_candidates() -> list:
    """
    Returns the ranked list (best first) of Gemini models to try for this
    request. Result is cached for the life of the process.

    If GEMINI_MODEL is set in .env, that's the *only* candidate — an
    explicit override means "use exactly this model", so there's no
    auto-fallback across other Gemini models (Groq fallback still applies
    on top if even that one call fails).

    Otherwise, lists every model available to this API key that supports
    generateContent and ranks them via _rank_model. Free-tier quotas are
    generally per-model-per-day, not shared across the whole project, so
    keeping the full list (instead of picking just one "best" model)
    lets _call_gemini() move on to the next candidate when one is
    exhausted, rather than jumping straight to Groq.

    Falls back to a single hardcoded default only if listing itself fails
    (e.g. transient network error) so the pipeline degrades gracefully
    instead of hard-failing.
    """
    global _discovered_models
    if _MODEL_OVERRIDE:
        return [_MODEL_OVERRIDE]
    if _discovered_models is not None:
        return _discovered_models

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
        _discovered_models = ["gemini-2.5-flash"]
        return _discovered_models

    if not candidates:
        print("[ai_keywords_utils] ❌ No models support generateContent for this "
              "API key; falling back to gemini-2.5-flash")
        _discovered_models = ["gemini-2.5-flash"]
        return _discovered_models

    excluded = [name for name in candidates if name in _KNOWN_INCOMPATIBLE_MODELS]
    if excluded:
        print(f"[ai_keywords_utils] ⏭️  Excluding {len(excluded)} known-incompatible "
              f"model(s) (reject system_instruction/JSON mode): {', '.join(excluded)}")
        candidates = [name for name in candidates if name not in _KNOWN_INCOMPATIBLE_MODELS]

    _discovered_models = sorted(candidates, key=_rank_model)
    print(f"[ai_keywords_utils] ✅ Ranked {len(_discovered_models)} candidate model(s); "
          f"will try in order starting with '{_discovered_models[0]}'")
    return _discovered_models


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


def _parse_topics_response(raw_text: str, video_duration: float) -> list:
    """
    Shared cleanup/parsing for both providers' raw text output into
    [{"keyword": str, "start": float}, ...], sorted by start time.
    Returns [] if the output can't be parsed as the expected JSON shape.
    """
    raw_text = (raw_text or "").strip()

    # Defensive cleanup in case the model wraps the JSON in a code fence
    # despite being asked for raw JSON.
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


_RETRYABLE_CODES = (429, 500, 503)
_RETRYABLE_SUBSTRINGS = (
    "RESOURCE_EXHAUSTED",
    "UNAVAILABLE",
    "INTERNAL",
    "INVALID_ARGUMENT",
    "429",
    "400",
    "500",
    "503",
)

# Some candidate models — despite technically supporting generateContent —
# aren't actually general-purpose text models at all: they're
# image/audio/video/robotics/agentic preview models (nano-banana-pro,
# lyria-*, veo-*, gemini-*-image, gemini-*-tts, gemini-*-computer-use,
# gemini-*-live, gemini-robotics-er-*, antigravity-preview, deep-research-*,
# etc.) that reject the plain "system_instruction + JSON text" request this
# pipeline always sends. Each rejects it with its own 400 INVALID_ARGUMENT
# message — e.g. "Developer instruction is not enabled for models/X", or
# "This model only supports Interactions API." — and new variants keep
# showing up as we work through the candidate list. Rather than chase each
# new message string one at a time, we treat *any* 400 as "this specific
# model can't do it, move on" — since our request shape never changes, a
# 400 here always means a model-capability mismatch, not a data problem
# that would fail identically everywhere. Worst case (a genuinely malformed
# request) this just means we burn through more candidates before falling
# through to Groq, instead of silently never trying Groq at all.
_MODEL_INCOMPATIBLE_CODE = 400


def _is_retryable_gemini_error(e: Exception) -> bool:
    """
    True for errors where a *different* model (or Groq) might well
    succeed: 429 quota exhaustion, a transient 500/503 server-side hiccup,
    or a 400 (this specific model rejecting a request shape every other
    candidate accepts fine — see _MODEL_INCOMPATIBLE_CODE above). False
    only for genuinely unexpected errors (e.g. an auth failure) that would
    fail identically on every model.
    """
    code = getattr(e, "code", None)
    if code in _RETRYABLE_CODES or code == _MODEL_INCOMPATIBLE_CODE:
        return True
    text = str(e)
    # Only check the front of the message, where the SDK puts the status
    # code/name, to avoid false positives from those digits/words showing
    # up incidentally later in an unrelated error detail string.
    head = text[:40]
    return any(s in head for s in _RETRYABLE_SUBSTRINGS)


def _call_gemini_one(user_content: str, model: str) -> str:
    """Calls one specific Gemini model. Returns raw text output, or raises
    QuotaExhaustedError if this model hit a retryable error (429 quota
    exhaustion, or a transient 500/503 server-side error) — either way,
    the caller should move on to the next model candidate rather than
    treating it as a hard failure."""
    client = _get_client()
    try:
        response = client.models.generate_content(
            model=model,
            contents=user_content,
            config={
                "system_instruction": _SYSTEM_PROMPT,
                "response_mime_type": "application/json",
                "temperature": 0.2,
            },
        )
    except Exception as e:
        if _is_retryable_gemini_error(e):
            raise QuotaExhaustedError(
                f"Gemini model '{model}' failed with a retryable error: {e}. "
                "This is quota exhaustion (429 RESOURCE_EXHAUSTED — check "
                "https://aistudio.google.com/apikey and "
                "https://ai.dev/rate-limit; if it mentions "
                "'free_tier_requests, limit: 0' this model has zero "
                "free-tier quota for this key and retrying won't help), a "
                "transient server-side overload (500/503) that often "
                "clears up on a different model or a bit later, or a "
                "permanent model-specific incompatibility (400, e.g. an "
                "experimental/preview model rejecting system_instruction) "
                "that a different model candidate simply won't hit."
            ) from e
        raise
    return response.text


def _call_gemini(user_content: str) -> str:
    """
    Tries each ranked Gemini model candidate in turn, skipping any already
    known (this run) to be quota-exhausted. Free-tier quotas are generally
    per-model-per-day rather than shared across the whole project, so a
    429 on e.g. gemini-2.0-flash doesn't necessarily mean gemini-2.5-flash-lite
    is exhausted too — this tries the next candidate before giving up on
    Gemini entirely and handing off to Groq.

    Raises QuotaExhaustedError only once every candidate model has failed
    with a retryable error (429 quota exhaustion or transient 500/503)
    (or if GEMINI_MODEL was set explicitly and that single model failed
    that way).
    """
    candidates = _get_model_candidates()
    last_err = None
    for model in candidates:
        if model in _exhausted_models:
            continue
        try:
            text = _call_gemini_one(user_content, model)
            if model != candidates[0]:
                print(f"[ai_keywords_utils] ✅ Succeeded with '{model}' "
                      f"(earlier candidate(s) failed this run)")
            return text
        except QuotaExhaustedError as e:
            print(f"[ai_keywords_utils] ⚠️  '{model}' failed ({e.__cause__}); "
                  f"trying next Gemini model candidate…")
            _exhausted_models.add(model)
            last_err = e
            continue

    # Every candidate model is exhausted (or was already marked so from an
    # earlier call this run) — nothing left to try on the Gemini side.
    raise last_err or QuotaExhaustedError(
        "All Gemini model candidates are quota-exhausted for this API key."
    )


def _call_groq(user_content: str) -> str:
    """Returns raw text output from the Groq fallback model."""
    client = _get_groq_client()
    response = client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    return response.choices[0].message.content


def extract_topics(title: str, segments: list) -> list:
    """
    Calls Gemini (primary) — or Groq as an automatic fallback if Gemini's
    quota is exhausted and GROQ_API_KEY is configured — to extract
    {keyword, start} topic markers from a Hebrew transcript. Returns a
    list of dicts, sorted by start time ascending:
      [{"keyword": str, "start": float}, ...]
    Returns [] if segments is empty or the model output can't be parsed.
    Raises QuotaExhaustedError if Gemini's quota is exhausted and either
    no Groq fallback is configured, or the Groq call also fails.
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

    try:
        raw_text = _call_gemini(user_content)
    except QuotaExhaustedError as quota_err:
        groq_client = _get_groq_client()
        if groq_client is None:
            raise  # no fallback configured — surface the original error
        print(f"[ai_keywords_utils] ⚠️  Gemini quota exhausted — "
              f"falling back to Groq ({_GROQ_MODEL})")
        try:
            raw_text = _call_groq(user_content)
        except Exception as groq_err:
            print(f"[ai_keywords_utils] ❌ Groq fallback also failed "
                  f"({type(groq_err).__name__}: {groq_err})")
            raise quota_err from groq_err

    return _parse_topics_response(raw_text, video_duration)
