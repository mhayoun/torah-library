#!/usr/bin/env python3
"""
main.py
-------
Single entry point that:
  1. Discovers playlists from the configured YouTube channels.
  2. Categorizes them by title (see playlist_utils.CATEGORY_MAPPING).
  3. Fetches every video inside each matched playlist (incrementally -
     only new videos are hit against the API; cached ones are reused).
  4. Writes the merged, deduplicated, sorted result to
     frontend/public/categorized_videos.json

This replaces the old standalone fetch_videos.py: that script used a
hardcoded CATEGORIES dict of playlist IDs, while this flow auto-discovers
playlists from the channel and categorizes them by title. The richer
per-video fields (duration, view_count, thumbnail) that fetch_videos.py
used to provide are now produced by playlist_videos_utils.py.

Requirements:
    pip install google-api-python-client python-dotenv yt-dlp

Usage:
    Set YOUTUBE_API_KEY in a .env file or as an environment variable.
    Run: python main.py
"""

import json
import os
from dotenv import load_dotenv

from playlist_utils import get_raw_playlists, categorize_playlists
from playlist_videos_utils import enrich_structured_playlists, OUTPUT_FILE

load_dotenv()

TARGET_URLS = [
    "https://www.youtube.com/@Rabbi_Aharon_Butbul/playlists",
    "https://www.youtube.com/@%D7%94%D7%A8%D7%91%D7%90%D7%94%D7%A8%D7%95%D7%9F%D7%91%D7%95%D7%98%D7%91%D7%95%D7%9C-%D7%A97%D7%9E/playlists",
]


def main():
    if not os.environ.get("YOUTUBE_API_KEY"):
        raise ValueError("YOUTUBE_API_KEY environment variable is not set.")

    # 1. Fetch raw playlist feeds
    print("Extracting playlists from YouTube...")
    raw_playlists = get_raw_playlists(TARGET_URLS)

    # 2. Categorize them using the custom utility rules
    print(f"Found {len(raw_playlists)} items. Categorizing...")
    structured_data = categorize_playlists(raw_playlists)

    # 3. Output results
    print("\nCategorized Playlists Result:")
    print(json.dumps(structured_data, ensure_ascii=False, indent=4))

    # 4. Extract the videos from YouTube for each found playlist
    final_data = enrich_structured_playlists(structured_data, skip_fallback=True)

    # 5. Write enriched dataset to disk (-> frontend/public/categorized_videos.json)
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=4)

    total = sum(len(videos) for videos in final_data.values())
    print(f"\n✨ Success! {total} videos saved to '{OUTPUT_FILE}'")


if __name__ == "__main__":
    main()
