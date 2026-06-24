# playlist_utils.py
import yt_dlp

DEBUG = True

# Category rules mapping: { "Category Name": [list of keywords to match] }
# NOTE: order matters - categorize_playlists checks categories in this order
# and stops at the first match. Keep more specific phrases ABOVE generic ones
# (e.g. a rabbi's name) to avoid accidental cross-matches.
CATEGORY_MAPPING = {
    "הלכה יומית": ["הלכה יומית"],
    "השיעור השבועי": ["השיעור השבועי", "הרב עובדיה יוסף בוטבול"],
    "שיחת חולין": ["שיחת חולין"],
    "דעת ותורה": ["דעת ותורה"],
    "הליכות עולם": ["הליכות עולם"]
}


def get_raw_playlists(urls):
    """Fetches all playlists from the provided YouTube channel URLs."""
    ydl_opts = {
        'extract_flat': 'in_playlist',
        'skip_download': True,
        'quiet': True
    }

    raw_entries = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for url in urls:
            try:
                result = ydl.extract_info(url, download=False)
                if result and 'entries' in result:
                    raw_entries.extend(result['entries'])
            except Exception as e:
                print(f"Error fetching from {url}: {e}")
    return raw_entries


def find_matching_categories(title):
    """
    Returns a list of ALL categories whose keywords appear in `title`.
    Used for debug purposes to catch ambiguous titles that match more
    than one category (the first one wins in categorize_playlists, but
    that may not be the "correct" one).
    """
    matches = []
    for category, keywords in CATEGORY_MAPPING.items():
        for keyword in keywords:
            if keyword in title:
                matches.append((category, keyword))
    return matches


def categorize_playlists(raw_entries):
    """Groups playlists into specified categories using title matching rules."""
    categorized = {category: [] for category in CATEGORY_MAPPING}
    categorized["אחר"] = []

    for entry in raw_entries:
        url = entry.get('url', '')
        _type = entry.get('_type', '')

        if _type != 'url' and 'playlist' not in url:
            continue

        title = entry.get('title', '')
        playlist_data = {"title": title, "url": url}

        all_matches = find_matching_categories(title)

        if DEBUG:
            if not all_matches:
                print(f"[DEBUG][categorize] '{title}' -> NO MATCH (אחר)")
            elif len(all_matches) > 1:
                # Ambiguous: title matches keywords from more than one category.
                # The first one (by CATEGORY_MAPPING order) wins - flag it so
                # you can see if that's actually the wrong choice.
                chosen_category, chosen_keyword = all_matches[0]
                others = ", ".join(f"{c} (kw='{k}')" for c, k in all_matches[1:])
                print(
                    f"[DEBUG][categorize] ⚠️ AMBIGUOUS '{title}' -> chose "
                    f"'{chosen_category}' (kw='{chosen_keyword}'), also matched: {others}"
                )
            else:
                category, keyword = all_matches[0]
                print(f"[DEBUG][categorize] '{title}' -> '{category}' (kw='{keyword}')")

        if all_matches:
            chosen_category = all_matches[0][0]
            categorized[chosen_category].append(playlist_data)
        else:
            categorized["אחר"].append(playlist_data)

    return categorized
