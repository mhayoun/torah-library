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


class GeminiUnavailableError(RuntimeError):
    """
    Base class: raised when Gemini could not fulfill the request through
    any candidate model. Two concrete causes, see subclasses below.
    Callers (extract_topics) catch this base class so both causes trigger
    the same Groq fallback.
    """
    pass


class QuotaExhaustedError(GeminiUnavailableError):
    """
    Raised when every Gemini candidate model returned 429 RESOURCE_EXHAUSTED
    and no working fallback (Groq) was available either. This is an
    account/project-level condition (free-tier quota set to 0, billing not
    linked, or a genuine rate limit) — NOT a problem with any particular
    video's transcript. Callers should stop processing further videos in
    the current run rather than retrying each one (they'll all fail
    identically) and should NOT record this as a per-video "error", since
    that would misleadingly suggest something is wrong with that specific
    video.
    """
    pass


class GeminiTransientError(GeminiUnavailableError):
    """
    Raised when a Gemini model returns a temporary server-side error (503
    UNAVAILABLE / "high demand", 500 INTERNAL, or 504 DEADLINE_EXCEEDED)
    rather than a quota problem. Unlike QuotaExhaustedError, this says
    nothing about the model's daily quota — it may well succeed on retry
    a few seconds later, or on the very next video. _call_gemini() treats
    it the same way as a 429 for the purposes of trying the next
    candidate model, but does NOT mark the model as exhausted for the
    rest of the run.
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


def _call_gemini_one(user_content: str, model: str) -> str:
    """Calls one specific Gemini model. Returns raw text output, or raises
    QuotaExhaustedError on a 429, or GeminiTransientError on a temporary
    server-side error (503/500/504)."""
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
        code = getattr(e, "code", None)
        text = str(e)
        if code == 429 or "RESOURCE_EXHAUSTED" in text or "429" in text[:20]:
            raise QuotaExhaustedError(
                f"Gemini model '{model}' quota exhausted (429 RESOURCE_EXHAUSTED). "
                "If the error mentions 'free_tier_requests, limit: 0', that means "
                "this API key's project has no free-tier quota granted at "
                "all for this model — retrying won't help. Check your plan/billing at "
                "https://aistudio.google.com/apikey and current usage at "
                "https://ai.dev/rate-limit; linking a billing account "
                "usually unlocks quota within minutes. If it's a genuine "
                "rate limit instead (a nonzero limit you've temporarily "
                "used up), just wait and re-run."
            ) from e
        if (code in (500, 503, 504) or
                any(m in text for m in ("UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED"))):
            raise GeminiTransientError(
                f"Gemini model '{model}' is temporarily unavailable "
                f"({type(e).__name__}: {e}). This is Google's server load, "
                "not a quota problem — often resolves within seconds."
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
    Gemini entirely and handing off to Groq. Temporary server errors
    (503/500/504) on a candidate are treated the same way — move on to
    the next model — but don't permanently mark that model exhausted,
    since it's likely to recover.

    Raises GeminiUnavailableError (QuotaExhaustedError or
    GeminiTransientError, whichever hit last) only once every candidate
    model has failed (or if GEMINI_MODEL was set explicitly and that
    single model failed).
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
                      f"(earlier candidate(s) exhausted this run)")
            return text
        except QuotaExhaustedError as e:
            print(f"[ai_keywords_utils] ⚠️  '{model}' quota exhausted (429); "
                  f"trying next Gemini model candidate…")
            _exhausted_models.add(model)  # daily quota — won't recover this run
            last_err = e
            continue
        except GeminiTransientError as e:
            print(f"[ai_keywords_utils] ⚠️  '{model}' temporarily unavailable "
                  f"(server-side); trying next Gemini model candidate…")
            # Not added to _exhausted_models: a transient 503 now doesn't
            # mean this model will still be down for the *next* video.
            last_err = e
            continue

    # Every candidate model failed (quota or transient) — nothing left to
    # try on the Gemini side this call.
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


def extract_topics(title: str, segments: list, provider: str = "gemini") -> list:
    """
    Extracts {keyword, start} topic markers from a Hebrew transcript,
    using whichever provider is tried first, with the *other* one as an
    automatic fallback if the first fails:

      provider="gemini" (default) — Gemini first; falls back to Groq if
        every Gemini candidate model fails (429 quota or transient
        server error) AND GROQ_API_KEY is configured.
      provider="groq" — Groq first; falls back to Gemini (with its own
        multi-model candidate ranking, see _call_gemini) if the Groq call
        fails, or if GROQ_API_KEY isn't configured at all.

    Either way, both providers are still attempted before giving up —
    this parameter only changes which one goes *first*, it never removes
    the safety net of trying the other one too.

    Returns a list of dicts, sorted by start time ascending:
      [{"keyword": str, "start": float}, ...]
    Returns [] if segments is empty or the model output can't be parsed.
    Raises GeminiUnavailableError (QuotaExhaustedError or
    GeminiTransientError) if neither provider could be used — e.g.
    Gemini exhausted and no Groq fallback configured/working, or (when
    provider="groq") Groq failed and Gemini also failed.
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

    if provider == "groq":
        raw_text = _extract_topics_groq_first(user_content)
    else:
        raw_text = _extract_topics_gemini_first(user_content)

    return _parse_topics_response(raw_text, video_duration)


def _extract_topics_gemini_first(user_content: str) -> str:
    """Gemini first, Groq as fallback. Original/default behavior."""
    try:
        return _call_gemini(user_content)
    except GeminiUnavailableError as gemini_err:
        groq_client = _get_groq_client()
        if groq_client is None:
            raise  # no fallback configured — surface the original error
        print(f"[ai_keywords_utils] ⚠️  Gemini unavailable ({type(gemini_err).__name__}) — "
              f"falling back to Groq ({_GROQ_MODEL})")
        try:
            return _call_groq(user_content)
        except Exception as groq_err:
            print(f"[ai_keywords_utils] ❌ Groq fallback also failed "
                  f"({type(groq_err).__name__}: {groq_err})")
            raise gemini_err from groq_err


def _extract_topics_groq_first(user_content: str) -> str:
    """
    Groq first, Gemini as fallback — mirror image of the default path,
    used when provider="groq" is requested.

    If GROQ_API_KEY isn't configured at all, there's nothing to try
    first, so this just goes straight to Gemini (with a heads-up print)
    rather than failing outright.
    """
    groq_client = _get_groq_client()
    if groq_client is None:
        print("[ai_keywords_utils] ⚠️  provider='groq' requested but GROQ_API_KEY "
              "isn't configured — using Gemini instead")
        return _call_gemini(user_content)

    try:
        return _call_groq(user_content)
    except Exception as groq_err:
        print(f"[ai_keywords_utils] ⚠️  Groq call failed "
              f"({type(groq_err).__name__}: {groq_err}) — falling back to Gemini")
        try:
            return _call_gemini(user_content)
        except GeminiUnavailableError as gemini_err:
            print(f"[ai_keywords_utils] ❌ Gemini fallback also failed "
                  f"({type(gemini_err).__name__}: {gemini_err})")
            raise gemini_err from groq_err
