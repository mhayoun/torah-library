"""
One-off cleanup: removes any already-stored "Private video" / "Deleted
video" stub entries from Redis (cours_full + cours_response), without
touching anything else or forcing a full re-sync.

This fixes data that was written BEFORE the fetch_videos_for_playlist /
fetch_videos_by_ids fix in playlist_videos_utils.py (which now skips
these stubs at fetch time, so this script should only ever need to run
once).

Usage:
    python3 util_purge_private_videos.py            # dry run, just reports
    python3 util_purge_private_videos.py --apply     # actually writes changes
"""
import asyncio
import json
import sys

from dotenv import load_dotenv
load_dotenv()

from main import get_redis

_UNAVAILABLE_TITLES = {"Private video", "Deleted video"}


async def main():
    apply = "--apply" in sys.argv

    r = await get_redis()
    raw = await r.get("cours_full")
    if not raw:
        print("cours_full is empty or missing — nothing to do.")
        await r.aclose()
        return

    all_videos = json.loads(raw)
    bad = [v for v in all_videos if v.get("title") in _UNAVAILABLE_TITLES]

    print(f"cours_full: {len(all_videos)} video(s) total")
    print(f"Found {len(bad)} private/deleted stub video(s):")
    for v in bad:
        print(f"  - {v.get('id')}  category={v.get('category')}  playlist={v.get('playlist')}")

    if not bad:
        await r.aclose()
        return

    if not apply:
        print("\nDry run only — re-run with --apply to remove these and rebuild cours_response.")
        await r.aclose()
        return

    cleaned = [v for v in all_videos if v.get("title") not in _UNAVAILABLE_TITLES]

    # Also drop any leftover transcript-cache keys for the removed IDs so
    # a stray transcript:<id> entry doesn't linger for a video nothing
    # references anymore.
    for v in bad:
        vid_id = v.get("id")
        if vid_id:
            await r.delete(f"transcript:{vid_id}")

    catalogue: dict[str, list] = {}
    for v in cleaned:
        cat = v.get("category", "אחר")
        catalogue.setdefault(cat, []).append(v)
    for cat in catalogue:
        catalogue[cat].sort(key=lambda x: x.get("upload_date") or "", reverse=True)

    last_sync = await r.get("last_sync_date")
    response_body = {
        "catalog": catalogue,
        "total": len(cleaned),
        "new": 0,
        "last_sync": last_sync,
    }

    await r.set("cours_full", json.dumps(cleaned))
    await r.set("cours_response", json.dumps(response_body))

    print(f"\nRemoved {len(bad)} video(s). cours_full now has {len(cleaned)} video(s).")
    await r.aclose()


if __name__ == "__main__":
    asyncio.run(main())
