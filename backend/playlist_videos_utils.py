import os
import json
import re
from datetime import datetime, timezone
from googleapiclient.discovery import build

from playlist_utils import CATEGORY_MAPPING, find_matching_categories

API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
DEBUG = True
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "categorized_videos.json")

_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc).isoformat()


# ── helpers (merged in from fetch_videos.py) ─────────────────────────────────

def iso_date(raw):
    """Convert YouTube publishedAt (2024-05-10T14:30:00Z) to an ISO string."""
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return raw


def parse_duration(iso):
    """Convert ISO 8601 duration (PT1H3M12S) -> HH:MM:SS or MM:SS."""
    if not iso:
        return "Unknown"
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return iso
    h, mn, s = (int(x or 0) for x in m.groups())
    return f"{h}:{mn:02d}:{s:02d}" if h else f"{mn}:{s:02d}"


def load_cached_videos_map(filename=OUTPUT_FILE):
    """
    Reads the file on disk and maps playlist URLs to their already saved video arrays.
    Returns: A dictionary of { playlist_url: [list_of_videos] } and a set of all video IDs.
    """
    cached_map = {}
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
                url = playlist.get("url")
                videos = playlist.get("videos", [])
                if url:
                    cached_map[url] = videos
                    for video in videos:
                        if "id" in video:
                            existing_ids.add(video.get("id"))

        if DEBUG:
            print(f"[DEBUG] Loaded cached data for {len(cached_map)} playlists containing {len(existing_ids)} unique video IDs.")
    except Exception as e:
        print(f"⚠️  Warning: Could not read existing cache file safely ({e}).")

    return cached_map, existing_ids


def extract_playlist_id(url):
    """Helper to extract the playlist ID from a YouTube URL."""
    match = re.search(r"[&?]list=([^&]+)", url)
    extracted = match.group(1) if match else url
    return extracted


def check_video_category_mismatch(video_title, current_category, playlist_title, playlist_url):
    """
    Debug helper: checks whether a video's OWN title matches a category
    keyword set that is DIFFERENT from the category its containing playlist
    was filed under. This is exactly how a 'הלכה יומית' video can end up
    listed inside 'השיעור השבועי' (or vice versa) - the playlist gets
    categorized by ITS title, but individual videos inside it aren't
    re-checked, so a stray/misplaced video silently inherits the wrong
    category.
    """
    if not video_title:
        return

    matches = find_matching_categories(video_title)
    matched_categories = {c for c, _ in matches}

    if matched_categories and current_category not in matched_categories:
        print(
            f"[DEBUG][video-mismatch] ⚠️ Video '{video_title}' looks like it "
            f"belongs to {sorted(matched_categories)}, but is filed under "
            f"'{current_category}' because it's inside playlist "
            f"'{playlist_title}' ({playlist_url})"
        )


def fetch_videos_for_playlist(playlist_url, existing_ids, category=None, playlist_title=None):
    """
    Hits YouTube API, checks for new videos, and breaks early when a duplicate
    is found (incremental update). For every NEW video, also fetches its
    duration/view_count via a batched videos.list() call, and (in DEBUG mode)
    checks whether the video's own title suggests it belongs to a different
    category than the one it was filed under.
    """
    playlist_id = extract_playlist_id(playlist_url)
    videos = []
    next_page_token = None
    should_continue = True

    try:
        youtube = build("youtube", "v3", developerKey=API_KEY)

        while should_continue:
            request = youtube.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token
            )
            response = request.execute()
            items = response.get("items", [])

            if not items:
                break

            # Figure out which items in this page are genuinely new BEFORE
            # making the (costlier) batched videos.list() details call.
            page_new_items = []
            for item in items:
                content_details = item.get("contentDetails", {})
                video_id = content_details.get("videoId")

                if video_id in existing_ids:
                    if DEBUG:
                        print(f"   [DEBUG] Hit known video ID: {video_id}. Stopping pagination early.")
                    should_continue = False
                    break

                page_new_items.append(item)

            if page_new_items:
                video_ids = [
                    it["contentDetails"]["videoId"]
                    for it in page_new_items
                    if it.get("contentDetails", {}).get("videoId")
                ]

                details_map = {}
                if video_ids:
                    details_resp = youtube.videos().list(
                        part="contentDetails,statistics",
                        id=",".join(video_ids),
                    ).execute()
                    details_map = {v["id"]: v for v in details_resp.get("items", [])}

                for item in page_new_items:
                    snippet = item.get("snippet", {})
                    content_details = item.get("contentDetails", {})
                    video_id = content_details.get("videoId")
                    title = snippet.get("title")

                    if DEBUG:
                        safe_title = (title or "").encode('utf-8', errors='replace').decode('utf-8')
                        print(f"   [DEBUG NEW ITEM] {safe_title}")

                    if category is not None:
                        check_video_category_mismatch(title, category, playlist_title, playlist_url)

                    details = details_map.get(video_id, {})
                    duration_raw = details.get("contentDetails", {}).get("duration", "")
                    view_count_raw = details.get("statistics", {}).get("viewCount")
                    thumbnails = snippet.get("thumbnails", {})

                    videos.append({
                        "id": video_id,
                        "title": title,
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "duration": parse_duration(duration_raw),
                        "view_count": int(view_count_raw) if view_count_raw else None,
                        "upload_date": iso_date(snippet.get("publishedAt")),
                        "thumbnail": (
                            thumbnails.get("medium") or thumbnails.get("default") or {}
                        ).get("url"),
                    })

            if not should_continue:
                break

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

    except Exception as e:
        print(f"❌ Failed to fetch updates for {playlist_url}: {e}")

    return videos


def enrich_structured_playlists(structured_data, skip_fallback=True):
    """
    Takes freshly categorized playlists, fetches all their videos,
    and returns a flat dict where each category key maps directly to
    a deduplicated list of video objects sorted by upload_date DESC:

        {
            "הלכה יומית": [ {id, title, url, duration, view_count, upload_date, thumbnail}, ... ],
            ...
        }
    """
    cached_playlists_map, existing_ids = load_cached_videos_map(OUTPUT_FILE)

    print("\nDeep scanning matched playlists for inner videos...")

    result = {}

    for category, playlists in structured_data.items():
        if skip_fallback and category == "אחר":
            continue
        if not playlists:
            continue

        print(f"\n📂 Processing Category: {category}")

        seen_ids = set()
        all_videos = []

        for playlist in playlists:
            playlist_url = playlist.get('url')
            playlist_title = playlist.get('title')
            print(f"   -> Scanning: '{playlist_title}'")

            old_videos = cached_playlists_map.get(playlist_url, [])
            new_videos = fetch_videos_for_playlist(
                playlist_url, existing_ids,
                category=category, playlist_title=playlist_title,
            )

            for video in (new_videos + old_videos):
                vid_id = video.get("id")
                if vid_id and vid_id not in seen_ids:
                    seen_ids.add(vid_id)
                    all_videos.append(video)

        # Sort newest-first; videos without a date fall to the bottom
        all_videos.sort(
            key=lambda v: v.get("upload_date") or _EPOCH,
            reverse=True,
        )

        result[category] = all_videos
        print(f"   ✅ {len(all_videos)} unique videos in '{category}'")

    return result
