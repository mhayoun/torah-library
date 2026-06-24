# debug_logger.py
"""
Structured debug logger that writes ONLY errors and problematic-video details
to a log file (debug.log). stdout is left for normal progress messages.

Usage:
    from debug_logger import DebugLogger
    logger = DebugLogger()                 # default: debug.log next to this file
    logger.log_video_error(...)
    logger.log_playlist_summary(...)
    logger.close()
"""

import os
import traceback
from datetime import datetime, timezone


class DebugLogger:
    def __init__(self, log_path: str | None = None):
        if log_path is None:
            log_path = os.path.join(os.path.dirname(__file__), "debug.log")
        self.log_path = log_path
        self._fh = open(log_path, "a", encoding="utf-8")
        self._write_header()

        # { playlist_url: {"title": str, "success": int, "fail": int, "errors": [str]} }
        self._stats: dict[str, dict] = {}

    # ── internal ─────────────────────────────────────────────────────────────

    def _ts(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _write(self, text: str):
        self._fh.write(text + "\n")
        self._fh.flush()

    def _write_header(self):
        self._write(
            f"\n{'=' * 72}\n"
            f"  RUN STARTED  {self._ts()}\n"
            f"{'=' * 72}"
        )

    def _ensure_playlist(self, playlist_url: str, playlist_title: str = ""):
        if playlist_url not in self._stats:
            self._stats[playlist_url] = {
                "title": playlist_title or playlist_url,
                "success": 0,
                "fail": 0,
                "found": 0,       # videos fetched from the API (new, before dedup)
                "added": 0,       # videos actually inserted into the final output
                "rerouted": 0,    # videos moved to a different category due to mismatch
                "errors": [],
            }
        elif playlist_title:
            # Keep the first non-empty title we see
            self._stats[playlist_url].setdefault("title", playlist_title)

    # ── public API ────────────────────────────────────────────────────────────

    def record_success(self, playlist_url: str, playlist_title: str = ""):
        """Call once per successfully processed video."""
        self._ensure_playlist(playlist_url, playlist_title)
        self._stats[playlist_url]["success"] += 1

    def record_found(self, playlist_url: str, playlist_title: str = "", count: int = 1):
        """Call with the number of videos fetched from the API for this playlist."""
        self._ensure_playlist(playlist_url, playlist_title)
        self._stats[playlist_url]["found"] += count

    def record_added(self, playlist_url: str, playlist_title: str = "", count: int = 1):
        """Call with the number of videos actually inserted into the final output."""
        self._ensure_playlist(playlist_url, playlist_title)
        self._stats[playlist_url]["added"] += count

    def record_rerouted(self, playlist_url: str, playlist_title: str = "", count: int = 1):
        """Call when a video was moved to a different category due to a mismatch."""
        self._ensure_playlist(playlist_url, playlist_title)
        self._stats[playlist_url]["rerouted"] += count

    def log_video_error(
        self,
        *,
        playlist_url: str,
        playlist_title: str = "",
        video_id: str = "",
        video_title: str = "",
        error: Exception | str | None = None,
        extra: str = "",
    ):
        """
        Log a problematic video. Also bumps the failure counter for the
        containing playlist so the per-playlist summary is accurate.
        """
        self._ensure_playlist(playlist_url, playlist_title)
        self._stats[playlist_url]["fail"] += 1

        lines = [
            f"[{self._ts()}] VIDEO ERROR",
            f"  Playlist : {playlist_title or playlist_url}",
            f"  PL URL   : {playlist_url}",
        ]
        if video_id:
            lines.append(f"  Video ID : {video_id}")
        if video_title:
            lines.append(f"  Title    : {video_title}")
        if error:
            if isinstance(error, Exception):
                lines.append(f"  Error    : {type(error).__name__}: {error}")
                tb = traceback.format_exc()
                if tb and tb.strip() != "NoneType: None":
                    lines.append(f"  Traceback:\n{tb.rstrip()}")
            else:
                lines.append(f"  Error    : {error}")
        if extra:
            lines.append(f"  Detail   : {extra}")
        lines.append("")  # blank separator

        block = "\n".join(lines)
        self._write(block)
        self._stats[playlist_url]["errors"].append(block)

    def log_category_mismatch(
        self,
        *,
        video_title: str,
        current_category: str,
        matched_categories: set,
        playlist_title: str,
        playlist_url: str,
    ):
        """Log a video whose own title suggests a different category."""
        self._ensure_playlist(playlist_url, playlist_title)
        # Mismatches are warnings, not hard failures – they don't bump the
        # fail counter but ARE written to the log so they're easy to audit.
        self._write(
            f"[{self._ts()}] CATEGORY MISMATCH WARNING\n"
            f"  Video    : {video_title}\n"
            f"  Filed as : {current_category}\n"
            f"  Looks like: {sorted(matched_categories)}\n"
            f"  Playlist : {playlist_title} ({playlist_url})\n"
        )

    def log_playlist_fetch_error(
        self,
        *,
        playlist_url: str,
        playlist_title: str = "",
        error: Exception | str,
    ):
        """Log an error that prevented fetching a playlist at all."""
        self._ensure_playlist(playlist_url, playlist_title)
        self._stats[playlist_url]["fail"] += 1

        if isinstance(error, Exception):
            err_str = f"{type(error).__name__}: {error}"
            tb = traceback.format_exc()
        else:
            err_str = str(error)
            tb = ""

        lines = [
            f"[{self._ts()}] PLAYLIST FETCH ERROR",
            f"  Playlist : {playlist_title or playlist_url}",
            f"  PL URL   : {playlist_url}",
            f"  Error    : {err_str}",
        ]
        if tb and tb.strip() != "NoneType: None":
            lines.append(f"  Traceback:\n{tb.rstrip()}")
        lines.append("")
        self._write("\n".join(lines))

    def log_category_reroute(
        self,
        *,
        video_title: str,
        video_id: str = "",
        original_category: str,
        target_category: str,
        playlist_title: str,
        playlist_url: str,
    ):
        """Log a video that was re-inserted into its correct category."""
        self._ensure_playlist(playlist_url, playlist_title)
        self._write(
            f"[{self._ts()}] CATEGORY REROUTE\n"
            f"  Video    : {video_title}\n"
            f"  ID       : {video_id}\n"
            f"  From     : {original_category}\n"
            f"  To       : {target_category}\n"
            f"  Playlist : {playlist_title} ({playlist_url})\n"
        )

    def log_playlist_summary(self, playlist_url: str, playlist_title: str = ""):
        """
        Write the success/fail counters for a single playlist.
        Call this after all videos in the playlist have been processed.
        """
        self._ensure_playlist(playlist_url, playlist_title)
        stats = self._stats[playlist_url]
        total = stats["success"] + stats["fail"]
        found = stats["found"]
        added = stats["added"]
        rerouted = stats["rerouted"]
        self._write(
            f"[{self._ts()}] PLAYLIST SUMMARY\n"
            f"  Playlist : {stats['title']}\n"
            f"  URL      : {playlist_url}\n"
            f"  Fetched  : {found} new videos found via API\n"
            f"  Added    : {added} videos inserted into final output\n"
            f"  Rerouted : {rerouted} videos moved to a different category\n"
            f"  Processed: {total} total  ✅ {stats['success']} succeeded  "
            f"❌ {stats['fail']} failed\n"
        )

    def log_run_summary(self):
        """Write a global summary at the end of the run."""
        total_ok = sum(s["success"] for s in self._stats.values())
        total_fail = sum(s["fail"] for s in self._stats.values())
        total_found = sum(s["found"] for s in self._stats.values())
        total_added = sum(s["added"] for s in self._stats.values())
        total_rerouted = sum(s["rerouted"] for s in self._stats.values())
        playlists_with_errors = [
            url for url, s in self._stats.items() if s["fail"] > 0
        ]
        playlists_with_reroutes = [
            url for url, s in self._stats.items() if s["rerouted"] > 0
        ]

        lines = [
            f"{'─' * 72}",
            f"[{self._ts()}] RUN SUMMARY",
            f"  Playlists processed : {len(self._stats)}",
            f"  Videos fetched (API): {total_found}",
            f"  Videos added (total): {total_added}",
            f"  Videos rerouted     : {total_rerouted}",
            f"  Videos succeeded    : {total_ok}",
            f"  Videos failed       : {total_fail}",
        ]
        if playlists_with_reroutes:
            lines.append("  Playlists with rerouted videos:")
            for url in playlists_with_reroutes:
                s = self._stats[url]
                lines.append(
                    f"    • {s['title']}  ({s['rerouted']} rerouted)"
                )
        if playlists_with_errors:
            lines.append("  Playlists with errors:")
            for url in playlists_with_errors:
                s = self._stats[url]
                lines.append(
                    f"    • {s['title']}  ({s['fail']} failed / "
                    f"{s['success'] + s['fail']} total)"
                )
        lines.append(f"{'─' * 72}\n")
        self._write("\n".join(lines))

    def close(self):
        """Flush and close the log file."""
        self._fh.flush()
        self._fh.close()
