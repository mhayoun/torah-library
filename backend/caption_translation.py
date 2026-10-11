"""
caption_translation.py
----------------------
Translates a video's timed Hebrew transcript segments into English, French
or Russian with Gemini, keeping one translated line per source segment so
the original timings can be reused as-is for on-video captions.

Exists because YouTube's own auto-translated captions (tlang=...) come back
429 for embedded players, so the frontend player renders these instead.

Segments are sent in batches; each batch is numbered and the model must
return exactly one translation per number, so a missing/garbled line in the
reply can't shift every later caption out of sync — it just comes back
empty for that one segment.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor

from ai_keywords_utils import _call_gemini

SUPPORTED_LANGUAGES = {
    "en": "English",
    "fr": "French",
    "ru": "Russian",
}

# ~150 segments ≈ 5 minutes of speech: enough surrounding context for the
# model to translate sentence fragments sensibly, small enough to stay well
# inside output limits and keep each call quick.
BATCH_SIZE = 150
MAX_PARALLEL_BATCHES = 4

# Longest transcript (in segments) we'll translate: ~450 segments ≈ 20 min
# of speech = 3 Gemini requests per language. Each request takes ~20-60s,
# and the free tier allows only ~20 requests/day per model, so hour-long
# lessons (~1300 segments, 9 requests) would both blow the 300s function
# limit and eat the daily quota the sync's topic extraction also needs.
# Raise via MAX_CAPTION_SEGMENTS on a paid Gemini key.
MAX_SEGMENTS = int(os.environ.get("MAX_CAPTION_SEGMENTS", "450"))

# Enforced via Gemini structured output: without it, Hebrew abbreviations
# like חז"ל occasionally leak unescaped quotes into the reply and the whole
# batch fails to parse.
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"i": {"type": "integer"}, "t": {"type": "string"}},
                "required": ["i", "t"],
            },
        },
    },
    "required": ["lines"],
}

_SYSTEM_PROMPT_TEMPLATE = """You translate auto-generated (speech-recognition) Hebrew captions of a Torah lecture by Rabbi Aharon Butbul into {language}.

Input: a JSON array of caption lines, each {{"i": <number>, "t": "<Hebrew text>"}}, in spoken order. Lines are fragments of continuous speech, often cut mid-sentence, and may contain recognition errors - use the surrounding lines to understand the meaning and fix obvious errors.

Output: a JSON object {{"lines": [{{"i": <number>, "t": "<translation>"}}, ...]}} with exactly one entry for every input "i", in the same order. Translate each line on its own (do not merge or move text between lines), keeping it short enough to read as a caption.

Keep well-known Hebrew/halachic terms in their common transliterated form where a {language}-speaking observant reader would expect them (e.g. Rosh Chodesh, Shabbat, Halacha, Ya'aleh VeYavo, Amida, Gemara, Shulchan Aruch), and render names of sages as commonly written in {language}."""


def _translate_batch(batch: list, language: str) -> list:
    """Translates one batch of segments. Returns translated strings in the
    same order (empty string for any line the model didn't return)."""
    payload = [{"i": i, "t": seg["text"]} for i, seg in enumerate(batch)]
    raw = _call_gemini(
        json.dumps(payload, ensure_ascii=False),
        system_prompt=_SYSTEM_PROMPT_TEMPLATE.format(language=language),
        response_schema=_RESPONSE_SCHEMA,
    )
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    lines = parsed.get("lines", []) if isinstance(parsed, dict) else parsed
    if not isinstance(lines, list):
        lines = []

    # Tolerate the shapes the model sometimes drifts into: "i" as a string,
    # or a bare list of strings (taken positionally).
    by_index = {}
    for pos, line in enumerate(lines):
        if isinstance(line, str):
            by_index[pos] = line.strip()
        elif isinstance(line, dict):
            try:
                idx = int(line.get("i", pos))
            except (TypeError, ValueError):
                idx = pos
            by_index[idx] = str(line.get("t") or "").strip()
    texts = [by_index.get(i, "") for i in range(len(batch))]

    missing = sum(1 for t in texts if not t)
    if missing:
        print(f"[caption_translation] {missing}/{len(batch)} line(s) untranslated "
              f"({language}); reply started: {str(raw)[:200]!r}")
    return texts


def translate_segments(segments: list, lang: str) -> list:
    """
    segments: [{"text", "start", "duration"}, ...] (Hebrew, from
              transcript_utils.fetch_hebrew_transcript).
    lang:     one of SUPPORTED_LANGUAGES.

    Returns [{"start", "duration", "text"}, ...] with the same timings and
    translated text. Segments the model left untranslated are dropped
    rather than shown blank.

    Raises ai_keywords_utils.GeminiUnavailableError if Gemini can't be used
    (quota exhausted / down) for any batch.
    """
    language = SUPPORTED_LANGUAGES[lang]
    batches = [segments[i:i + BATCH_SIZE] for i in range(0, len(segments), BATCH_SIZE)]
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_BATCHES) as pool:
        results = list(pool.map(lambda b: _translate_batch(b, language), batches))

    out = []
    for batch, texts in zip(batches, results):
        for seg, text in zip(batch, texts):
            if text:
                out.append({"start": seg["start"], "duration": seg["duration"], "text": text})
    return out
