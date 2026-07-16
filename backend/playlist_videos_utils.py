import os
import json
import re
from datetime import datetime, timezone
from googleapiclient.discovery import build
from pyluach import dates as heb_dates

from playlist_utils import CATEGORY_MAPPING, find_matching_categories
from debug_logger import DebugLogger

API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
DEBUG   = True

# Legacy path kept for backward-compat (local script mode still writes here)
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "categorized_videos.json")

_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc).isoformat()

# ── Hebraic year extraction ─────────────────────────────────────────────────
#
# Fully dynamic — no hardcoded list of years, so next year (and every year
# after) works automatically without code changes.
#
# Hebrew year abbreviations look like: תש + [tens letter] + ["] + [units letter]
#   e.g. תשפ"ו (5786) = תש(700) + פ(80) + gershayim + ו(6)
#        תשע"ט (5779) = תש(700) + ע(70) + gershayim + ט(9)
# or, when there's no units digit, just: תש + [tens letter]
#   e.g. תש"פ / תשפ (5780) = תש(700) + פ(80)   [our canonical form drops
#        the quote for this case: 'תשפ', per spec]
#
# FORMAT RULE:
#   4-letter year (תש + tens + units)  -> תש + tens + '"' + units   e.g. תשפ"ו
#   3-letter year (תש + tens only)     -> תש + tens                e.g. תשפ
TENS_LETTERS_REGULAR = "יכלמנסעפצק"   # 10, 20, 30 ... 100
TENS_LETTERS_FINAL   = "ךםןףץ"        # final-letter forms (word-end spelling)
TENS_LETTERS         = TENS_LETTERS_REGULAR + TENS_LETTERS_FINAL
UNITS_LETTERS        = "אבגדהוזחט"     # 1..9

_FINAL_TO_REGULAR = {"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"}

# All quote-like characters that can stand in for the gershayim (״)/geresh
# (׳) used in Hebrew numeral notation.
_HEB_YEAR_QUOTES = "\"'\u05f3\u05f4\u2018\u2019\u201c\u201d"

# 4-letter form: תש + tens + (mandatory quote) + units — e.g. תשפ"ו, תשצ"א.
# The quote is mandatory here since it's what distinguishes a year from an
# ordinary 4-letter word.
_HEB_YEAR_QUOTED_RE = re.compile(
    r"(ה)?תש([" + TENS_LETTERS + r"])[" + _HEB_YEAR_QUOTES + r"]+([" + UNITS_LETTERS + r"])(?![א-ת])"
)

# 3-letter form: תש + tens only — e.g. תשפ, תש"פ, התשפ.
# Requires either the definite-article "ה" prefix or a quote character to be
# confident this is a year and not an ordinary word (e.g. תשע = "nine",
# תשליך = "tashlich", תשלישי = "third").
_HEB_YEAR_BARE_RE = re.compile(
    r"(ה)?תש([" + _HEB_YEAR_QUOTES + r"])?([" + TENS_LETTERS + r"])(?![א-ת])"
)


def _normalize_letter(letter):
    """Converts a final-form letter (e.g. ץ) to its regular form (e.g. צ)."""
    return _FINAL_TO_REGULAR.get(letter, letter)


def extract_hebraic_year(title):
    """
    Extracts the Hebrew (hebraic) year from a video/playlist title, e.g.:
        'ג' תשרי התשפ"ו - יום כנגד שנה...'   -> 'תשפ"ו'
        'הלכה יומית תשפ"ו'                    -> 'תשפ"ו'
        'משהו משנת תש"פ'                       -> 'תשפ'

    Fully dynamic (no hardcoded year list) — works for any past or future
    Hebrew year without code changes. Returns None if no confident match is
    found (never guesses/invents a year). When several valid matches exist,
    prefers the one with the definite-article "ה" prefix (the common form
    in these titles, e.g. "התשפ\"ו").
    """
    if not title:
        return None

    best = None  # (canonical, has_prefix)

    # Prefer the unambiguous 4-letter/quoted form first.
    for m in _HEB_YEAR_QUOTED_RE.finditer(title):
        prefix, tens, units = m.group(1), m.group(2), m.group(3)
        canonical = "תש" + _normalize_letter(tens) + '"' + units
        has_prefix = bool(prefix)
        if best is None or (has_prefix and not best[1]):
            best = (canonical, has_prefix)
    if best:
        return best[0]

    # Fall back to the 3-letter/bare form (needs ה prefix or a quote).
    for m in _HEB_YEAR_BARE_RE.finditer(title):
        prefix, quote, tens = m.group(1), m.group(2), m.group(3)
        if not prefix and not quote:
            continue  # too ambiguous - could be an ordinary word
        canonical = "תש" + _normalize_letter(tens)
        has_prefix = bool(prefix)
        if best is None or (has_prefix and not best[1]):
            best = (canonical, has_prefix)

    return best[0] if best else None


# ── Hebraic year fallback (computed from upload_date) ──────────────────────
#
# Used only when extract_hebraic_year() couldn't find a year in the title
# or playlist title. Converts the video's Gregorian upload date to a Hebrew
# year and formats it using the same canonical convention as above
# (תש + tens + '"' + units, or תש + tens with no quote when units == 0).
# Only years 5700-5799 (i.e. the תש... range) are supported, matching the
# format the rest of the codebase expects; anything outside that range
# returns None rather than guessing at an unsupported letter pattern.

_HEB_YEAR_BASE = 5700  # first year in the תש... range


def _heb_remainder_to_letters(remainder):
    """Converts a 0-99 remainder (year - 5700) into תש + Hebrew letters."""
    if remainder <= 0:
        return "תש"

    tens_digit  = (remainder // 10) * 10
    units_digit = remainder % 10

    # Avoid spelling out God's name: 15 -> ט"ו (not י"ה), 16 -> ט"ז (not י"ו)
    if tens_digit == 10 and units_digit == 5:
        return 'תש' + 'ט' + '"' + 'ו'
    if tens_digit == 10 and units_digit == 6:
        return 'תש' + 'ט' + '"' + 'ז'

    tens_letter = TENS_LETTERS_REGULAR[tens_digit // 10 - 1] if tens_digit else ""

    if units_digit == 0:
        return "תש" + tens_letter

    units_letter = UNITS_LETTERS[units_digit - 1]
    return "תש" + tens_letter + '"' + units_letter


def compute_hebraic_year_from_date(upload_date):
    """
    Computes the canonical Hebrew year string (e.g. 'תשפ"ו') from an ISO
    Gregorian upload_date string. Returns None if upload_date is missing/
    unparseable or the resulting Hebrew year falls outside the supported
    5700-5799 (תש...) range.
    """
    if not upload_date:
        return None
    try:
        dt = datetime.fromisoformat(upload_date.replace("Z", "+00:00"))
    except ValueError:
        return None

    try:
        heb_year = heb_dates.GregorianDate(dt.year, dt.month, dt.day).to_heb().year
    except Exception:
        return None

    remainder = heb_year - _HEB_YEAR_BASE
    if not (0 <= remainder <= 99):
        return None  # outside the תש... range this codebase's format supports

    return _heb_remainder_to_letters(remainder)


# ── helpers ───────────────────────────────────────────────────────────────────

# YouTube's API doesn't omit private/deleted videos from playlistItems
# responses - it returns a stub item instead, with snippet.title set to
# the literal English string "Private video" or "Deleted video" (this
# happens regardless of the API's requested locale) and no real content
# (no thumbnails, no real description). videos().list() typically omits
# such videos entirely for non-owners, but can occasionally return the
# same stub, so this check is applied wherever a title is read from
# either endpoint.
_UNAVAILABLE_TITLES = {"Private video", "Deleted video"}


def _is_unavailable_item(snippet):
    """True if this playlistItems/videos snippet is a private/deleted stub."""
    return (snippet or {}).get("title") in _UNAVAILABLE_TITLES


def iso_date(raw):
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return raw


def parse_duration(iso):
    if not iso:
        return "Unknown"
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return iso
    h, mn, s = (int(x or 0) for x in m.groups())
    return f"{h}:{mn:02d}:{s:02d}" if h else f"{mn}:{s:02d}"


def load_cached_videos_map(filename=OUTPUT_FILE):
    """
    Reads the on-disk JSON and returns:
      cached_map   : { playlist_url: [video, ...] }
      existing_ids : set of all known video IDs
    Only used in LOCAL (script) mode. In API mode, existing_ids is passed
    directly from Redis by main.py.
    """
    cached_map   = {}
    existing_ids = set()

    if not os.path.exists(filename):
        return cached_map, existing_ids

    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)

        for category, playlists in data.items():
            if not isinstance(playlists, list):
                continue
            for playlist in playlists:
                url    = playlist.get("url")
                videos = playlist.get("videos", [])
                if url:
                    cached_map[url] = videos
                    for video in videos:
                        if "id" in video:
                            existing_ids.add(video["id"])

        if DEBUG:
            print(f"[DEBUG] Loaded cached data: {len(cached_map)} playlists, {len(existing_ids)} IDs.")
    except Exception as e:
        print(f"⚠️  Warning: Could not read cache file ({e}).")

    return cached_map, existing_ids


def extract_playlist_id(url):
    match = re.search(r"[&?]list=([^&]+)", url)
    return match.group(1) if match else url


def check_video_category_mismatch(video_title, current_category, playlist_title, playlist_url, logger=None):
    if not video_title:
        return set()
    matches = find_matching_categories(video_title)
    matched_categories = {c for c, _ in matches}
    if matched_categories and current_category not in matched_categories:
        msg = (
            f"[DEBUG][video-mismatch] ⚠️ Video '{video_title}' looks like "
            f"{sorted(matched_categories)}, filed under '{current_category}' "
            f"(playlist '{playlist_title}')"
        )
        if DEBUG:
            print(msg)
        if logger:
            logger.log_category_mismatch(
                video_title=video_title,
                current_category=current_category,
                matched_categories=matched_categories,
                playlist_title=playlist_title,
                playlist_url=playlist_url,
            )
        return matched_categories
    return set()


def fetch_videos_for_playlist(
    playlist_url,
    existing_ids,
    category=None,
    playlist_title=None,
    logger=None,
    required_keyword=None,
):
    """
    Fetches NEW videos only from a playlist where new videos are appended
    at the END (oldest-first order on YouTube).

    Strategy:
      1. Paginate through ALL pages to reach the last page.
      2. On the last page, scan items in REVERSE order (end → beginning).
      3. Collect items whose ID is not in existing_ids.
      4. Stop scanning the moment a known ID is hit — everything before it
         (earlier in the playlist) is already stored.
      5. Batch-fetch details only for the collected new IDs.

    This is the inverse of the previous strategy which assumed newest-first
    ordering. Because the playlist is oldest-first, new videos appear at
    the end, so we must reach the last page before we can detect them.

    `required_keyword`, if given, is a per-VIDEO title check applied on top
    of playlist-level filtering (see CHANNEL_CATEGORY_OVERRIDES in
    playlist_utils.py): a playlist can pass the override because its own
    title has the keyword, but still contain unrelated videos saved into
    it whose titles don't. Any such video is skipped entirely - not added
    to `videos`, not to `mismatched`, not to any category.

    Returns (videos, mismatched_videos).
    """
    playlist_id = extract_playlist_id(playlist_url)
    videos      = []
    mismatched  = []

    try:
        youtube = build("youtube", "v3", developerKey=API_KEY)

        # ── Phase 1: paginate to collect ALL pages of raw items ───────────────
        all_items  = []
        next_page  = None
        page_count = 0

        while True:
            try:
                resp = youtube.playlistItems().list(
                    part="snippet,contentDetails",
                    playlistId=playlist_id,
                    maxResults=50,
                    pageToken=next_page,
                ).execute()
                page_count += 1
            except Exception as exc:
                msg = (
                    f"Phase-1 page {page_count+1} fetch failed. "
                    f"playlistId={playlist_id}. "
                    f"Likely quota exhausted (403) or invalid key (400). "
                    f"Error: {type(exc).__name__}: {exc}"
                )
                print(f"❌ {msg}")
                if logger:
                    logger.log_playlist_fetch_error(
                        playlist_url=playlist_url,
                        playlist_title=playlist_title or "",
                        error=exc,
                    )
                    logger.log_video_error(
                        playlist_url=playlist_url,
                        playlist_title=playlist_title or "",
                        extra=msg,
                    )
                break

            items = resp.get("items", [])

            if page_count == 1 and not items:
                total_results = resp.get("pageInfo", {}).get("totalResults", "?")
                msg = (
                    f"Page 1 returned 0 items for playlist '{playlist_title}' "
                    f"(id={playlist_id}). "
                    f"YouTube pageInfo.totalResults={total_results}. "
                    f"Causes: quota exhausted, wrong ID, or private playlist."
                )
                print(f"⚠️  {msg}")
                if logger:
                    logger.log_video_error(
                        playlist_url=playlist_url,
                        playlist_title=playlist_title or "",
                        extra=msg,
                    )
                break

            if not items:
                break

            all_items.extend(items)

            next_page = resp.get("nextPageToken")
            if not next_page:
                break   # reached the last page

        if DEBUG:
            print(f"   [DEBUG] Paginated {page_count} page(s), {len(all_items)} total items.")

        if logger:
            logger.record_found(
                playlist_url=playlist_url,
                playlist_title=playlist_title or "",
                count=len(all_items),
            )

        if not all_items:
            return videos, mismatched

        # ── Phase 2: find every item not already known ─────────────────────
        # No early-stop / boundary assumption: all_items was already fully
        # paginated above (that's where the real API cost was paid), so
        # simply checking every single item against existing_ids costs
        # nothing extra beyond a few thousand dict lookups. This is correct
        # no matter WHERE in the playlist a new video was inserted — front,
        # back, or shuffled into the middle by the owner — instead of
        # assuming new videos only ever land at one edge.
        new_items = [
            item for item in all_items
            if item.get("contentDetails", {}).get("videoId")
            and item["contentDetails"]["videoId"] not in existing_ids
            and not _is_unavailable_item(item.get("snippet"))
        ]

        skipped_unavailable = sum(
            1 for item in all_items
            if item.get("contentDetails", {}).get("videoId")
            and item["contentDetails"]["videoId"] not in existing_ids
            and _is_unavailable_item(item.get("snippet"))
        )
        if skipped_unavailable and DEBUG:
            print(f"   [DEBUG] ⛔ Skipped {skipped_unavailable} private/deleted stub item(s).")

        if DEBUG:
            print(f"   [DEBUG] {len(new_items)} new item(s) found (full scan, no early-stop).")

        if not new_items:
            return videos, mismatched

        # ── Phase 3: batch-fetch details for new IDs only ─────────────────────
        vid_ids = [
            it["contentDetails"]["videoId"]
            for it in new_items
            if it.get("contentDetails", {}).get("videoId")
        ]
        details_map = {}
        # videos.list's `id` filter only accepts up to 50 IDs per request;
        # sending more (e.g. all 233 new IDs at once) makes YouTube reject
        # the whole request with a 400 invalidFilters error. Chunk into
        # batches of 50 so one large playlist can't fail entirely.
        DETAILS_BATCH_SIZE = 50
        for i in range(0, len(vid_ids), DETAILS_BATCH_SIZE):
            chunk = vid_ids[i:i + DETAILS_BATCH_SIZE]
            try:
                det = youtube.videos().list(
                    part="contentDetails,statistics",
                    id=",".join(chunk),
                ).execute()
                details_map.update({v["id"]: v for v in det.get("items", [])})
            except Exception as det_exc:
                print(f"   ⚠️  Details batch failed (IDs {i}-{i+len(chunk)-1}): {det_exc}")
                if logger:
                    logger.log_video_error(
                        playlist_url=playlist_url,
                        playlist_title=playlist_title or "",
                        error=det_exc,
                        extra="details batch; IDs: " + ", ".join(chunk),
                    )

        # ── Phase 4: build video objects ──────────────────────────────────────
        for item in new_items:
            snippet = item.get("snippet", {})
            vid_id  = item["contentDetails"].get("videoId")
            title   = snippet.get("title")

            # Per-video keyword check (see docstring): the playlist itself
            # may have qualified for a channel override, but that doesn't
            # guarantee every video inside it is actually relevant.
            if required_keyword and required_keyword not in (title or ""):
                if DEBUG:
                    print(
                        f"   [DEBUG] ⛔ SKIPPED video '{title}' ({vid_id}) - playlist "
                        f"'{playlist_title}' passed the channel override but this "
                        f"video's own title is missing required keyword "
                        f"'{required_keyword}'; not added to any category."
                    )
                continue

            try:
                det    = details_map.get(vid_id, {})
                thumbs = snippet.get("thumbnails", {})
                upload_date = iso_date(snippet.get("publishedAt"))

                hebraic_year = extract_hebraic_year(title) or extract_hebraic_year(playlist_title)
                if not hebraic_year:
                    hebraic_year = compute_hebraic_year_from_date(upload_date)
                    if hebraic_year:
                        detail = f"computed {hebraic_year} from upload_date {upload_date}"
                    else:
                        detail = f"fallback from upload_date {upload_date} also failed"
                    msg = (
                        f"[DEBUG][hebraic-year] Could not extract year from title "
                        f"'{title}' or playlist '{playlist_title}' (video {vid_id}); {detail}."
                    )
                    if DEBUG:
                        print(msg)
                    if logger:
                        logger.log_video_error(
                            playlist_url=playlist_url,
                            playlist_title=playlist_title or "",
                            video_id=vid_id or "",
                            video_title=title or "",
                            extra=msg,
                        )

                video_obj = {
                    "id":          vid_id,
                    "title":       title,
                    "url":         f"https://www.youtube.com/watch?v={vid_id}",
                    "duration":    parse_duration(det.get("contentDetails", {}).get("duration", "")),
                    "view_count":  int(det["statistics"]["viewCount"]) if det.get("statistics", {}).get("viewCount") else None,
                    "upload_date": upload_date,
                    "thumbnail":   (thumbs.get("medium") or thumbs.get("default") or {}).get("url"),
                    "category":    category or "אחר",
                    "playlist":    playlist_title,
                    "hebraic_year": hebraic_year,
                }

                if logger:
                    logger.record_found(playlist_url=playlist_url, playlist_title=playlist_title or "")

                target_cats = set()
                if category:
                    target_cats = check_video_category_mismatch(
                        title, category, playlist_title, playlist_url, logger=logger
                    )

                if target_cats:
                    mismatched.append((video_obj, target_cats))
                else:
                    videos.append(video_obj)

                if logger:
                    logger.record_success(playlist_url=playlist_url, playlist_title=playlist_title or "")

            except Exception as exc:
                print(f"   ❌ Error processing '{title}' ({vid_id}): {exc}")
                if logger:
                    logger.log_video_error(
                        playlist_url=playlist_url,
                        playlist_title=playlist_title or "",
                        video_id=vid_id or "",
                        video_title=title or "",
                        error=exc,
                    )

    except Exception as exc:
        print(f"❌ Failed to fetch playlist {playlist_url}: {exc}")
        if logger:
            logger.log_playlist_fetch_error(
                playlist_url=playlist_url,
                playlist_title=playlist_title or "",
                error=exc,
            )

    return videos, mismatched


def fetch_videos_by_ids(
    video_entries,
    existing_ids,
    category=None,
    source_label=None,
    logger=None,
):
    """
    Fetches video details directly by video ID via videos().list() - no
    playlistItems() call, since there's no real playlist involved.

    Used for entries flagged kind="video" in categorize_playlists, i.e.
    videos discovered on a channel's '/streams' or '/videos' tab (yt-dlp
    lists these as raw videos, not named playlists, so they can't be fed
    to fetch_videos_for_playlist which expects a `list=` playlist ID).

    `video_entries` is a list of playlist_data dicts containing at least
    "video_id" (as produced by categorize_playlists).

    Returns (videos, mismatched) - same shape as fetch_videos_for_playlist.
    """
    videos = []
    mismatched = []

    new_ids = [
        e["video_id"] for e in video_entries
        if e.get("video_id") and e["video_id"] not in existing_ids
    ]
    if DEBUG:
        print(f"   [DEBUG] fetch_videos_by_ids: {len(video_entries)} entries, "
              f"{len(new_ids)} not yet in existing_ids.")
    if not new_ids:
        return videos, mismatched

    try:
        youtube = build("youtube", "v3", developerKey=API_KEY)

        details_map = {}
        DETAILS_BATCH_SIZE = 50
        for i in range(0, len(new_ids), DETAILS_BATCH_SIZE):
            chunk = new_ids[i:i + DETAILS_BATCH_SIZE]
            try:
                resp = youtube.videos().list(
                    part="snippet,contentDetails,statistics",
                    id=",".join(chunk),
                ).execute()
                for item in resp.get("items", []):
                    details_map[item["id"]] = item
            except Exception as exc:
                print(f"   ⚠️  videos.list batch failed (IDs {i}-{i+len(chunk)-1}): {exc}")
                if logger:
                    logger.log_video_error(
                        playlist_url=source_label or "",
                        playlist_title=source_label or "",
                        error=exc,
                        extra="fetch_videos_by_ids batch; IDs: " + ", ".join(chunk),
                    )

        for vid_id in new_ids:
            item = details_map.get(vid_id)
            if not item:
                continue  # video deleted/private/unavailable - just skip it

            snippet = item.get("snippet", {})
            if _is_unavailable_item(snippet):
                if DEBUG:
                    print(f"   [DEBUG] ⛔ Skipped private/deleted stub video ({vid_id}).")
                continue

            title = snippet.get("title")

            try:
                thumbs = snippet.get("thumbnails", {})
                upload_date = iso_date(snippet.get("publishedAt"))

                hebraic_year = extract_hebraic_year(title)
                if not hebraic_year:
                    hebraic_year = compute_hebraic_year_from_date(upload_date)

                video_obj = {
                    "id":           vid_id,
                    "title":        title,
                    "url":          f"https://www.youtube.com/watch?v={vid_id}",
                    "duration":     parse_duration(item.get("contentDetails", {}).get("duration", "")),
                    "view_count":   int(item["statistics"]["viewCount"]) if item.get("statistics", {}).get("viewCount") else None,
                    "upload_date":  upload_date,
                    "thumbnail":    (thumbs.get("medium") or thumbs.get("default") or {}).get("url"),
                    "category":     category or "אחר",
                    "playlist":     source_label,
                    "hebraic_year": hebraic_year,
                }

                if logger:
                    logger.record_found(playlist_url=source_label or "", playlist_title=source_label or "")

                target_cats = set()
                if category:
                    target_cats = check_video_category_mismatch(
                        title, category, source_label, source_label, logger=logger
                    )

                if target_cats:
                    mismatched.append((video_obj, target_cats))
                else:
                    videos.append(video_obj)

                if logger:
                    logger.record_success(playlist_url=source_label or "", playlist_title=source_label or "")

            except Exception as exc:
                print(f"   ❌ Error processing '{title}' ({vid_id}): {exc}")
                if logger:
                    logger.log_video_error(
                        playlist_url=source_label or "",
                        playlist_title=source_label or "",
                        video_id=vid_id or "",
                        video_title=title or "",
                        error=exc,
                    )

    except Exception as exc:
        print(f"❌ Failed to fetch videos by ID for '{source_label}': {exc}")
        if logger:
            logger.log_playlist_fetch_error(
                playlist_url=source_label or "",
                playlist_title=source_label or "",
                error=exc,
            )

    return videos, mismatched


def enrich_structured_playlists(
    structured_data,
    skip_fallback=True,
    logger=None,
    existing_ids=None,          # NEW: passed from Redis in API mode
    prefetched=None,            # NEW: optional {playlist_url: (new_vids, mismatched)}
                                 # cache to avoid re-hitting the YouTube API for
                                 # playlists that were already fetched elsewhere
                                 # in the same run (e.g. debug_sync.py STEP 3).
):
    """
    Fetches new videos for all playlists and returns a flat catalogue dict:
      { category: [video, ...] }

    In API mode, pass `existing_ids` (a set of known video IDs from Redis).
    In local script mode, existing_ids is loaded from the on-disk JSON.

    Videos whose title signals a different category are rerouted.
    """
    # In local script mode, fall back to reading from disk
    if existing_ids is None:
        _, existing_ids = load_cached_videos_map(OUTPUT_FILE)

    print("\nScanning playlists for new videos...")

    result:    dict[str, list] = {cat: [] for cat in structured_data}
    seen_ids:  dict[str, set]  = {cat: set() for cat in structured_data}

    pending_reroutes = []  # [(video_obj, target_cat, orig_cat, pl_title, pl_url)]

    for category, playlists in structured_data.items():
        if skip_fallback and category == "אחר":
            continue
        if not playlists:
            continue

        print(f"\n📂 {category}")

        real_playlists = [p for p in playlists if p.get("kind") != "video"]
        loose_videos   = [p for p in playlists if p.get("kind") == "video"]

        for playlist in real_playlists:
            pl_url   = playlist.get("url")
            pl_title = playlist.get("title")
            print(f"   → {pl_title}")

            if prefetched is not None and pl_url in prefetched:
                new_vids, mismatched = prefetched[pl_url]
            else:
                new_vids, mismatched = fetch_videos_for_playlist(
                    pl_url,
                    existing_ids,
                    category=category,
                    playlist_title=pl_title,
                    logger=logger,
                    required_keyword=playlist.get("required_keyword"),
                )

            added = 0
            for v in new_vids:
                vid_id = v.get("id")
                if vid_id and vid_id not in seen_ids[category]:
                    seen_ids[category].add(vid_id)
                    result[category].append(v)
                    added += 1

            for v, target_cats in mismatched:
                target = next((c for c in structured_data if c in target_cats), None)
                if target:
                    pending_reroutes.append((v, target, category, pl_title, pl_url))
                else:
                    vid_id = v.get("id")
                    if vid_id and vid_id not in seen_ids[category]:
                        seen_ids[category].add(vid_id)
                        result[category].append(v)
                        added += 1

            if logger:
                logger.record_added(playlist_url=pl_url, playlist_title=pl_title or "", count=added)
                logger.log_playlist_summary(playlist_url=pl_url, playlist_title=pl_title or "")

            print(f"      +{added} new videos added to '{category}'")

        # Videos discovered on a '/streams' or '/videos' channel tab - these
        # aren't playlists, so fetch them directly by video ID in one batch.
        if loose_videos:
            label = f"{category} (direct videos)"
            print(f"   → {label} ({len(loose_videos)} candidate video(s))")

            new_vids, mismatched = fetch_videos_by_ids(
                loose_videos,
                existing_ids,
                category=category,
                source_label=label,
                logger=logger,
            )

            added = 0
            for v in new_vids:
                vid_id = v.get("id")
                if vid_id and vid_id not in seen_ids[category]:
                    seen_ids[category].add(vid_id)
                    result[category].append(v)
                    added += 1

            for v, target_cats in mismatched:
                target = next((c for c in structured_data if c in target_cats), None)
                if target:
                    pending_reroutes.append((v, target, category, label, label))
                else:
                    vid_id = v.get("id")
                    if vid_id and vid_id not in seen_ids[category]:
                        seen_ids[category].add(vid_id)
                        result[category].append(v)
                        added += 1

            if logger:
                logger.record_added(playlist_url=label, playlist_title=label, count=added)
                logger.log_playlist_summary(playlist_url=label, playlist_title=label)

            print(f"      +{added} new videos added to '{category}'")

    # Apply reroutes
    for v, target_cat, orig_cat, pl_title, pl_url in pending_reroutes:
        vid_id = v.get("id")
        if target_cat not in seen_ids:
            seen_ids[target_cat] = set()
        if target_cat not in result:
            result[target_cat] = []
        if vid_id and vid_id in seen_ids[target_cat]:
            continue
        if vid_id:
            seen_ids[target_cat].add(vid_id)
        v["category"] = target_cat  # ← ADD THIS LINE
        result[target_cat].append(v)
        print(f"   ↪  Rerouted '{v.get('title')}': '{orig_cat}' → '{target_cat}'")
        if logger:
            logger.record_rerouted(playlist_url=pl_url, playlist_title=pl_title or "")
            logger.log_category_reroute(
                video_title=v.get("title", ""),
                video_id=vid_id or "",
                original_category=orig_cat,
                target_category=target_cat,
                playlist_title=pl_title,
                playlist_url=pl_url,
            )

    # Sort newest-first per category
    for cat in result:
        result[cat].sort(key=lambda x: x.get("upload_date") or _EPOCH, reverse=True)
        if result[cat]:
            print(f"   ✅ {len(result[cat])} videos in '{cat}'")

    return result
