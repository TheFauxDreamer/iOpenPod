"""
PC Library Cache – scans a local music folder and provides indexed data
in the same dict format as iTunesDBCache so the UI widgets can consume
either source interchangeably.

Uses SyncEngine.pc_library.PCLibrary for the actual file scanning and
metadata extraction.  Results are cached to a JSON file on disk so
subsequent launches only need to re-scan files whose mtime changed.

Architecture (cache-first):
  1. load_from_disk() — instant startup from JSON cache
  2. start_scan()    — diff-based background scan (only reads changed files)
"""

import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, pyqtSlot, QThreadPool
from PyQt6.QtGui import QPixmap, QImage

logger = logging.getLogger(__name__)

# ── Cache directory ────────────────────────────────────────────────────────

_CACHE_DIR: Optional[str] = None


def _get_cache_dir() -> str:
    """Return (and lazily create) the cache directory for PC library data."""
    global _CACHE_DIR
    if _CACHE_DIR is None:
        base = os.path.join(os.path.expanduser("~"), ".iopenpod")
        _CACHE_DIR = base
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return _CACHE_DIR


def _art_cache_dir() -> str:
    """Return (and lazily create) the artwork thumbnail cache directory."""
    d = os.path.join(_get_cache_dir(), "art_cache")
    os.makedirs(d, exist_ok=True)
    return d


# ── PCTrack → dict conversion ─────────────────────────────────────────────

def _pctrack_to_dict(track) -> dict:
    """Convert a PCTrack dataclass to a dict with the same keys used by
    the iTunesDB parser, so grid/list widgets work unchanged.
    """
    return {
        "Title": track.title,
        "Artist": track.artist,
        "Album": track.album,
        "Album Artist": track.album_artist or track.artist,
        "Genre": track.genre or "",
        "year": track.year or 0,
        "length": track.duration_ms,
        "size": track.size,
        "bitrate": track.bitrate or 0,
        "sampleRate": track.sample_rate or 0,
        "trackNumber": track.track_number or 0,
        "discNumber": track.disc_number or 0,
        "rating": track.rating or 0,
        "playCount": 0,
        "Composer": track.composer or "",
        "Comment": track.comment or "",
        "Grouping": track.grouping or "",
        # PC-specific fields (not in iTunesDB)
        "_pc_path": track.path,
        "_pc_relative_path": track.relative_path,
        "_pc_art_hash": track.art_hash,
        "_pc_mtime": track.mtime,
        "_pc_extension": track.extension,
        "_pc_needs_transcoding": track.needs_transcoding,
    }


def _dict_to_cache_entry(d: dict) -> dict:
    """Slim down a track dict for JSON persistence (only serialisable fields)."""
    return {k: v for k, v in d.items() if isinstance(v, (str, int, float, bool, type(None)))}


# ── Artwork helpers ────────────────────────────────────────────────────────

def _extract_and_cache_art(file_path: str, art_hash: Optional[str]) -> Optional[str]:
    """Extract embedded art from *file_path*, save as a JPEG thumbnail,
    and return the cache file path.  Returns None if no art found.
    """
    if not art_hash:
        return None

    thumb_path = os.path.join(_art_cache_dir(), f"{art_hash}.jpg")
    if os.path.exists(thumb_path):
        return thumb_path  # Already cached

    try:
        from ArtworkDB_Writer.art_extractor import extract_art
        art_bytes = extract_art(file_path)
        if not art_bytes:
            return None
        # Resize to a thumbnail (152×152 matches grid art size)
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(art_bytes))
        img.thumbnail((152, 152), Image.Resampling.LANCZOS)
        img = img.convert("RGB")
        img.save(thumb_path, "JPEG", quality=85)
        return thumb_path
    except Exception as e:
        logger.debug("Art extraction failed for %s: %s", file_path, e)
        return None


def get_pc_artwork(art_hash: Optional[str]) -> Optional[QPixmap]:
    """Load a cached artwork thumbnail as a QPixmap.  Returns None if not cached."""
    if not art_hash:
        return None
    thumb_path = os.path.join(_art_cache_dir(), f"{art_hash}.jpg")
    if not os.path.exists(thumb_path):
        return None
    pm = QPixmap(thumb_path)
    return pm if not pm.isNull() else None


# ── Background diff-scan worker ───────────────────────────────────────────

class _DiffScanWorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    # (added_tracks: list[dict], removed_paths: list[str])
    incremental_update = pyqtSignal(object, object)
    progress = pyqtSignal(int, int)  # current, total


class _DiffScanWorker(QRunnable):
    """Diff-based scan: only reads metadata for new/modified files."""

    def __init__(self, music_folder: str, cached_entries: dict):
        """
        Args:
            music_folder: Path to the music folder.
            cached_entries: {path: (mtime, track_dict)} from disk cache.
        """
        super().__init__()
        self.music_folder = music_folder
        self.cached_entries = cached_entries  # path -> (mtime, dict)
        self.signals = _DiffScanWorkerSignals()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @pyqtSlot()
    def run(self):
        try:
            from SyncEngine.pc_library import PCLibrary
            library = PCLibrary(self.music_folder)

            # Phase 1: Fast stat scan — collect {path: (mtime, ext)} on disk
            disk_files: dict[str, tuple[float, str]] = {}
            stat_count = 0
            for path, mtime, ext in library.stat_scan():
                if self._cancelled:
                    return
                disk_files[path] = (mtime, ext)
                stat_count += 1
                if stat_count % 5000 == 0:
                    self.signals.progress.emit(stat_count, 0)

            logger.info("Stat scan found %d files on disk", len(disk_files))

            # Phase 2: Compute diff
            cached_paths = set(self.cached_entries.keys())
            disk_paths = set(disk_files.keys())

            removed_paths = list(cached_paths - disk_paths)
            new_paths = disk_paths - cached_paths
            # Modified = path exists in both but mtime changed
            modified_paths = set()
            for path in cached_paths & disk_paths:
                disk_mtime = disk_files[path][0]
                cached_mtime = self.cached_entries[path][0]
                if abs(disk_mtime - cached_mtime) >= 0.01:
                    modified_paths.add(path)

            needs_read = new_paths | modified_paths
            logger.info(
                "Diff: %d new, %d modified, %d removed, %d unchanged",
                len(new_paths), len(modified_paths), len(removed_paths),
                len(cached_paths & disk_paths) - len(modified_paths),
            )

            if not needs_read and not removed_paths:
                # Nothing changed — emit empty update
                self.signals.incremental_update.emit([], [])
                return

            # Phase 3: Read metadata only for new/modified files
            added_tracks: list[dict] = []
            total_to_read = len(needs_read)
            current = 0
            for path in needs_read:
                if self._cancelled:
                    return
                current += 1
                if current % 100 == 0:
                    self.signals.progress.emit(current, total_to_read)
                try:
                    track = library._read_track(Path(path))
                    if track:
                        d = _pctrack_to_dict(track)
                        _extract_and_cache_art(track.path, track.art_hash)
                        added_tracks.append(d)
                except Exception as e:
                    logger.debug("Failed to read %s: %s", path, e)

            self.signals.incremental_update.emit(added_tracks, removed_paths)

        except Exception as e:
            logger.error("Diff scan failed: %s", e, exc_info=True)
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


# ── Legacy full-scan worker (for first-time scan with no cache) ───────────

class _FullScanWorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    result = pyqtSignal(object)  # list[dict] — final complete result
    partial_result = pyqtSignal(object)  # list[dict] — incremental batch
    progress = pyqtSignal(int, int)  # current, total

_PARTIAL_BATCH_SIZE = 2000


class _FullScanWorker(QRunnable):
    """Full scan for first-time use (no disk cache exists)."""

    def __init__(self, music_folder: str):
        super().__init__()
        self.music_folder = music_folder
        self.signals = _FullScanWorkerSignals()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @pyqtSlot()
    def run(self):
        try:
            from SyncEngine.pc_library import PCLibrary
            library = PCLibrary(self.music_folder)

            all_tracks: list[dict] = []
            batch: list[dict] = []

            def on_progress(current: int, total: int, track):
                self.signals.progress.emit(current, total)

            for pc_track in library.scan(progress_callback=on_progress):
                if self._cancelled:
                    break

                d = _pctrack_to_dict(pc_track)
                _extract_and_cache_art(pc_track.path, pc_track.art_hash)

                all_tracks.append(d)
                batch.append(d)

                if len(batch) >= _PARTIAL_BATCH_SIZE:
                    self.signals.partial_result.emit(list(batch))
                    batch.clear()

            if batch:
                self.signals.partial_result.emit(list(batch))
                batch.clear()

            logger.info("Full scan complete: %d tracks", len(all_tracks))
            self.signals.result.emit(all_tracks)
        except Exception as e:
            logger.error("Full scan failed: %s", e, exc_info=True)
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


# ── PCLibraryCache singleton ───────────────────────────────────────────────

class PCLibraryCache(QObject):
    """Singleton cache for PC music library data.

    Mirrors the iTunesDBCache API so the UI widgets can consume either
    source.  Supports instant startup from disk cache + diff-based
    background scan for changes.
    """

    data_ready = pyqtSignal()
    scan_progress = pyqtSignal(int, int)  # current, total
    scan_finished = pyqtSignal()          # emitted once when scan fully done

    _instance: "PCLibraryCache | None" = None

    @classmethod
    def get_instance(cls) -> "PCLibraryCache":
        if cls._instance is None:
            cls._instance = PCLibraryCache()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._tracks: list[dict] = []
        self._track_by_path: dict[str, dict] = {}  # path -> track dict (fast lookup)
        self._music_folder: str = ""
        self._is_loading: bool = False
        self._is_ready: bool = False
        self._lock = threading.Lock()
        self._worker: _DiffScanWorker | _FullScanWorker | None = None
        # Pre-computed indexes
        self._album_index: dict = {}       # (album, artist) -> [tracks]
        self._album_only_index: dict = {}  # album -> [tracks]
        self._artist_index: dict = {}      # artist -> [tracks]
        self._genre_index: dict = {}       # genre -> [tracks]
        # Pre-computed item lists for grid display (Phase 2)
        self._album_items: list[dict] | None = None
        self._artist_items: list[dict] | None = None
        self._genre_items: list[dict] | None = None
        # Track whether the last scan found changes (avoids unnecessary rebuilds)
        self._scan_had_changes: bool = False

    # ── Public API ─────────────────────────────────────────────

    def is_ready(self) -> bool:
        with self._lock:
            return self._is_ready

    def is_loading(self) -> bool:
        with self._lock:
            return self._is_loading

    def cancel_scan(self):
        """Cancel a running scan."""
        if self._worker:
            self._worker.cancel()

    def get_tracks(self) -> list[dict]:
        with self._lock:
            return list(self._tracks)

    def get_albums(self) -> list:
        """Return a list of album dicts (mimics iTunesDBCache.get_albums
        which returns mhla entries).  We synthesise them from the index.
        """
        with self._lock:
            albums = []
            for (album, artist), tracks in self._album_index.items():
                albums.append({
                    "Album (Used by Album Item)": album,
                    "Artist (Used by Album Item)": artist,
                })
            return albums

    def get_album_index(self) -> dict:
        with self._lock:
            return dict(self._album_index)

    def get_album_only_index(self) -> dict:
        with self._lock:
            return dict(self._album_only_index)

    def get_artist_index(self) -> dict:
        with self._lock:
            return dict(self._artist_index)

    def get_genre_index(self) -> dict:
        with self._lock:
            return dict(self._genre_index)

    def get_music_folder(self) -> str:
        return self._music_folder

    # ── Pre-computed item lists (Phase 2) ─────────────────────

    def get_album_items(self) -> list[dict]:
        """Return pre-computed album items for grid display."""
        with self._lock:
            if self._album_items is None:
                self._album_items = self._build_album_items()
            return self._album_items

    def get_artist_items(self) -> list[dict]:
        """Return pre-computed artist items for grid display."""
        with self._lock:
            if self._artist_items is None:
                self._artist_items = self._build_artist_items()
            return self._artist_items

    def get_genre_items(self) -> list[dict]:
        """Return pre-computed genre items for grid display."""
        with self._lock:
            if self._genre_items is None:
                self._genre_items = self._build_genre_items()
            return self._genre_items

    def _invalidate_item_lists(self):
        """Mark item lists as stale so they get rebuilt on next access."""
        self._album_items = None
        self._artist_items = None
        self._genre_items = None

    def _build_album_items(self) -> list[dict]:
        """Build album items list from indexes (runs under lock)."""
        from GUI.widgets.formatters import get_album_format_tag

        items = []
        for (album, artist), tracks in self._album_index.items():
            if not tracks:
                continue

            album = album or "Unknown Album"
            artist = artist or "Unknown Artist"
            mhiiLink = tracks[0].get("mhiiLink")
            pc_art_hash = tracks[0].get("_pc_art_hash")
            track_count = len(tracks)
            year = next((t.get("year") for t in tracks if t.get("year")), None)
            total_length_ms = sum(t.get("length", 0) for t in tracks)
            format_tag = get_album_format_tag(tracks)

            subtitle_parts = [artist]
            if year and year > 0:
                subtitle_parts.append(str(year))
            subtitle_parts.append(f"{track_count} tracks")
            if format_tag:
                subtitle_parts.append(format_tag)

            items.append({
                "title": album,
                "subtitle": " · ".join(subtitle_parts),
                "album": album,
                "artist": artist,
                "year": year,
                "mhiiLink": mhiiLink,
                "_pc_art_hash": pc_art_hash,
                "_format_tag": format_tag,
                "category": "Albums",
                "filter_key": "Album",
                "filter_value": album,
                "track_count": track_count,
                "total_length_ms": total_length_ms,
            })

        return sorted(items, key=lambda x: (x.get("title") or "").lower())

    def _build_artist_items(self) -> list[dict]:
        """Build artist items list from indexes (runs under lock)."""
        from GUI.widgets.formatters import get_album_format_tag

        items = []
        for artist, tracks in self._artist_index.items():
            track_count = len(tracks)
            mhiiLink = next((t.get("mhiiLink") for t in tracks if t.get("mhiiLink")), None)
            pc_art_hash = next((t.get("_pc_art_hash") for t in tracks if t.get("_pc_art_hash")), None)
            album_count = len(set(t.get("Album", "") for t in tracks))
            total_plays = sum(t.get("playCount", 0) for t in tracks)
            format_tag = get_album_format_tag(tracks)

            subtitle_parts = []
            if album_count > 1:
                subtitle_parts.append(f"{album_count} albums")
            subtitle_parts.append(f"{track_count} tracks")
            if total_plays > 0:
                subtitle_parts.append(f"{total_plays} plays")
            if format_tag:
                subtitle_parts.append(format_tag)

            items.append({
                "title": artist,
                "subtitle": " · ".join(subtitle_parts),
                "mhiiLink": mhiiLink,
                "_pc_art_hash": pc_art_hash,
                "category": "Artists",
                "filter_key": "Artist",
                "filter_value": artist,
                "track_count": track_count,
                "album_count": album_count,
                "total_plays": total_plays,
            })

        return sorted(items, key=lambda x: (x.get("title") or "").lower())

    def _build_genre_items(self) -> list[dict]:
        """Build genre items list from indexes (runs under lock)."""
        from GUI.widgets.formatters import get_album_format_tag

        items = []
        for genre, tracks in self._genre_index.items():
            track_count = len(tracks)
            mhiiLink = next((t.get("mhiiLink") for t in tracks if t.get("mhiiLink")), None)
            pc_art_hash = next((t.get("_pc_art_hash") for t in tracks if t.get("_pc_art_hash")), None)
            artist_count = len(set(t.get("Artist", "") for t in tracks))
            total_length_ms = sum(t.get("length", 0) for t in tracks)
            total_hours = total_length_ms / (1000 * 60 * 60)
            format_tag = get_album_format_tag(tracks)

            subtitle_parts = []
            if artist_count > 1:
                subtitle_parts.append(f"{artist_count} artists")
            subtitle_parts.append(f"{track_count} tracks")
            if total_hours >= 1:
                subtitle_parts.append(f"{total_hours:.1f} hours")
            if format_tag:
                subtitle_parts.append(format_tag)

            items.append({
                "title": genre,
                "subtitle": " · ".join(subtitle_parts),
                "mhiiLink": mhiiLink,
                "_pc_art_hash": pc_art_hash,
                "category": "Genres",
                "filter_key": "Genre",
                "filter_value": genre,
                "track_count": track_count,
                "artist_count": artist_count,
                "total_length_ms": total_length_ms,
            })

        return sorted(items, key=lambda x: (x.get("title") or "").lower())

    # ── Instant startup from disk cache ───────────────────────

    def load_from_disk(self, music_folder: str) -> int:
        """Load cached data from disk JSON file into memory.

        Populates _tracks, builds indexes, sets _is_ready = True.
        Returns the number of tracks loaded (0 if no cache file).
        This is synchronous and fast (just JSON parsing + index building).
        """
        if not music_folder:
            return 0

        self._music_folder = music_folder
        cache_path = self._cache_file_path(music_folder)

        if not os.path.exists(cache_path):
            return 0

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("Failed to load disk cache: %s", e)
            return 0

        tracks = data.get("tracks", [])
        if not tracks:
            return 0

        with self._lock:
            self._tracks = tracks
            self._track_by_path = {t.get("_pc_path", ""): t for t in tracks if t.get("_pc_path")}
            self._album_index.clear()
            self._album_only_index.clear()
            self._artist_index.clear()
            self._genre_index.clear()
            self._index_tracks(tracks)
            # Pre-build item lists now so first grid load doesn't block
            self._album_items = self._build_album_items()
            self._artist_items = self._build_artist_items()
            self._genre_items = self._build_genre_items()
            self._is_ready = True

        logger.info("Loaded %d tracks from disk cache (instant startup)", len(tracks))
        return len(tracks)

    # ── Scanning ───────────────────────────────────────────────

    def start_scan(self, music_folder: str):
        """Start a background scan of the given music folder.

        If we have a disk cache, uses a fast diff-based scan (stat only for
        unchanged files). Otherwise, does a full scan with mutagen.
        """
        if not music_folder or not os.path.isdir(music_folder):
            logger.warning("Invalid music folder: %s", music_folder)
            return

        with self._lock:
            if self._is_loading:
                return
            self._is_loading = True
            self._music_folder = music_folder

        # Use already-loaded track data if available (avoids re-reading JSON)
        existing: dict = {}
        with self._lock:
            if self._track_by_path:
                for path, track in self._track_by_path.items():
                    mtime = track.get("_pc_mtime", 0)
                    existing[path] = (mtime, track)

        if not existing:
            existing = self._load_disk_cache_entries(music_folder)

        if existing:
            # Diff-based scan — only read metadata for new/modified files
            worker = _DiffScanWorker(music_folder, existing)
            self._worker = worker
            worker.signals.incremental_update.connect(self._on_incremental_update)
            worker.signals.error.connect(self._on_scan_error)
            worker.signals.progress.connect(self.scan_progress.emit)
            worker.signals.finished.connect(self._on_diff_scan_finished)
            QThreadPool.globalInstance().start(worker)
        else:
            # No cache — full scan
            worker = _FullScanWorker(music_folder)
            self._worker = worker
            worker.signals.partial_result.connect(self._on_partial_result)
            worker.signals.result.connect(self._on_full_scan_complete)
            worker.signals.error.connect(self._on_scan_error)
            worker.signals.progress.connect(self.scan_progress.emit)
            worker.signals.finished.connect(lambda: None)  # handled by result/error
            QThreadPool.globalInstance().start(worker)

    def clear(self):
        """Clear all cached data."""
        with self._lock:
            self._tracks.clear()
            self._track_by_path.clear()
            self._album_index.clear()
            self._album_only_index.clear()
            self._artist_index.clear()
            self._genre_index.clear()
            self._invalidate_item_lists()
            self._is_ready = False
            self._is_loading = False

    # ── Internal ───────────────────────────────────────────────

    def _index_tracks(self, tracks: list[dict]):
        """Add tracks to the in-memory indexes (caller holds no lock)."""
        for track in tracks:
            album = track.get("Album", "Unknown Album")
            artist = track.get("Artist", "Unknown Artist")
            album_artist = track.get("Album Artist") or artist
            genre = track.get("Genre", "")

            self._album_index.setdefault((album, album_artist), []).append(track)
            self._album_only_index.setdefault(album, []).append(track)
            self._artist_index.setdefault(artist, []).append(track)
            if genre:
                self._genre_index.setdefault(genre, []).append(track)

    def _remove_tracks_by_paths(self, paths: set[str]):
        """Remove tracks from _tracks and all indexes by their file paths."""
        if not paths:
            return
        # Remove from _tracks list
        self._tracks = [t for t in self._tracks if t.get("_pc_path", "") not in paths]
        # Remove from path lookup
        for p in paths:
            self._track_by_path.pop(p, None)
        # Rebuild indexes from scratch (simpler than surgical removal)
        self._album_index.clear()
        self._album_only_index.clear()
        self._artist_index.clear()
        self._genre_index.clear()
        self._index_tracks(self._tracks)

    def _on_partial_result(self, batch: list[dict]):
        """Called with each incremental batch of tracks during full scanning."""
        with self._lock:
            self._tracks.extend(batch)
            for t in batch:
                path = t.get("_pc_path", "")
                if path:
                    self._track_by_path[path] = t
            self._index_tracks(batch)
            self._invalidate_item_lists()
            self._is_ready = True  # Content available after first batch

        self.data_ready.emit()

    def _on_full_scan_complete(self, tracks: list[dict]):
        """Called when full background scan finishes successfully."""
        self._scan_had_changes = True  # Full scan always produces new data
        with self._lock:
            self._is_loading = False
            self._worker = None
            self._invalidate_item_lists()

        # Save to disk cache in a background thread
        music_folder = self._music_folder
        threading.Thread(
            target=self._save_disk_cache,
            args=(music_folder, tracks),
            daemon=True,
        ).start()

        self.scan_finished.emit()
        self.data_ready.emit()

    def scan_had_changes(self) -> bool:
        """Return True if the last completed scan found any changes."""
        return self._scan_had_changes

    def _on_incremental_update(self, added_tracks: list[dict], removed_paths: list[str]):
        """Called when diff scan finds changes."""
        has_changes = bool(added_tracks) or bool(removed_paths)
        self._scan_had_changes = has_changes

        with self._lock:
            if removed_paths:
                # Remove deleted/modified tracks
                # (modified files appear in both removed_paths and added_tracks)
                self._remove_tracks_by_paths(set(removed_paths))

            if added_tracks:
                self._tracks.extend(added_tracks)
                for t in added_tracks:
                    path = t.get("_pc_path", "")
                    if path:
                        self._track_by_path[path] = t
                self._index_tracks(added_tracks)

            if has_changes:
                self._invalidate_item_lists()

        if has_changes:
            # Save updated cache to disk
            music_folder = self._music_folder
            tracks = list(self._tracks)
            threading.Thread(
                target=self._save_disk_cache,
                args=(music_folder, tracks),
                daemon=True,
            ).start()
            self.data_ready.emit()

    def _on_diff_scan_finished(self):
        """Called when diff scan worker completes."""
        with self._lock:
            self._is_loading = False
            self._worker = None
        self.scan_finished.emit()

    def _on_scan_error(self, error_msg: str):
        """Called when background scan fails."""
        with self._lock:
            self._is_loading = False
            self._worker = None
        logger.error("PC library scan error: %s", error_msg)

    # ── Disk cache persistence ─────────────────────────────────

    def _cache_file_path(self, music_folder: str) -> str:
        """Return path to the JSON cache file for a given music folder."""
        folder_hash = hashlib.md5(music_folder.encode()).hexdigest()[:12]
        return os.path.join(_get_cache_dir(), f"pc_library_{folder_hash}.json")

    def _load_disk_cache_entries(self, music_folder: str) -> dict:
        """Load existing cache from disk.  Returns path -> (mtime, dict)."""
        cache_path = self._cache_file_path(music_folder)
        result: dict = {}
        if not os.path.exists(cache_path):
            return result
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for entry in data.get("tracks", []):
                path = entry.get("_pc_path", "")
                mtime = entry.get("_pc_mtime", 0)
                if path:
                    result[path] = (mtime, entry)
            logger.info("Loaded PC library cache entries: %d", len(result))
        except Exception as e:
            logger.warning("Failed to load PC library cache: %s", e)
        return result

    def _save_disk_cache(self, music_folder: str, tracks: list[dict]):
        """Save scan results to disk for incremental loading."""
        cache_path = self._cache_file_path(music_folder)
        try:
            data = {
                "music_folder": music_folder,
                "track_count": len(tracks),
                "tracks": [_dict_to_cache_entry(t) for t in tracks],
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, separators=(",", ":"))
            logger.info("Saved PC library cache: %d tracks", len(tracks))
        except Exception as e:
            logger.warning("Failed to save PC library cache: %s", e)
