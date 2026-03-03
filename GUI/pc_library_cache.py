"""
PC Library Cache – scans a local music folder and provides indexed data
in the same dict format as iTunesDBCache so the UI widgets can consume
either source interchangeably.

Uses SyncEngine.pc_library.PCLibrary for the actual file scanning and
metadata extraction.  Results are cached to a JSON file on disk so
subsequent launches only need to re-scan files whose mtime changed.
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


# ── Background scan worker ─────────────────────────────────────────────────

class _ScanWorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    result = pyqtSignal(object)  # list[dict] — final complete result
    partial_result = pyqtSignal(object)  # list[dict] — incremental batch
    progress = pyqtSignal(int, int)  # current, total

# How many tracks to accumulate before emitting a partial result batch
_PARTIAL_BATCH_SIZE = 500


class _ScanWorker(QRunnable):
    """Scans a music folder in a background thread."""

    def __init__(self, music_folder: str, existing_cache: dict):
        super().__init__()
        self.music_folder = music_folder
        self.existing_cache = existing_cache  # path -> (mtime, dict)
        self.signals = _ScanWorkerSignals()
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
            reused = 0

            def on_progress(current: int, total: int, track):
                self.signals.progress.emit(current, total)

            for pc_track in library.scan(progress_callback=on_progress):
                if self._cancelled:
                    break

                # Check if we can reuse the cached entry
                cached = self.existing_cache.get(pc_track.path)
                if cached and abs(cached[0] - pc_track.mtime) < 0.01:
                    d = cached[1]
                    reused += 1
                else:
                    d = _pctrack_to_dict(pc_track)
                    # Extract and cache artwork thumbnail
                    _extract_and_cache_art(pc_track.path, pc_track.art_hash)

                all_tracks.append(d)
                batch.append(d)

                # Emit partial result every _PARTIAL_BATCH_SIZE tracks
                if len(batch) >= _PARTIAL_BATCH_SIZE:
                    self.signals.partial_result.emit(list(batch))
                    batch.clear()

            # Emit any remaining tracks in the last partial batch
            if batch:
                self.signals.partial_result.emit(list(batch))
                batch.clear()

            logger.info(
                "PC library scan complete: %d tracks (%d reused from cache)",
                len(all_tracks), reused,
            )
            self.signals.result.emit(all_tracks)
        except Exception as e:
            logger.error("PC library scan failed: %s", e, exc_info=True)
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


# ── PCLibraryCache singleton ───────────────────────────────────────────────

class PCLibraryCache(QObject):
    """Singleton cache for PC music library data.

    Mirrors the iTunesDBCache API so the UI widgets can consume either
    source.  Scans a local folder in a background thread and builds the
    same album/artist/genre indexes.
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
        self._music_folder: str = ""
        self._is_loading: bool = False
        self._is_ready: bool = False
        self._lock = threading.Lock()
        self._worker: _ScanWorker | None = None
        # Pre-computed indexes
        self._album_index: dict = {}       # (album, artist) -> [tracks]
        self._album_only_index: dict = {}  # album -> [tracks]
        self._artist_index: dict = {}      # artist -> [tracks]
        self._genre_index: dict = {}       # genre -> [tracks]

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

    # ── Scanning ───────────────────────────────────────────────

    def start_scan(self, music_folder: str):
        """Start a background scan of the given music folder."""
        if not music_folder or not os.path.isdir(music_folder):
            logger.warning("Invalid music folder: %s", music_folder)
            return

        with self._lock:
            if self._is_loading:
                return
            self._is_loading = True
            self._music_folder = music_folder

        # Load any existing cache from disk for incremental scanning
        existing = self._load_disk_cache(music_folder)

        worker = _ScanWorker(music_folder, existing)
        self._worker = worker
        worker.signals.partial_result.connect(self._on_partial_result)
        worker.signals.result.connect(self._on_scan_complete)
        worker.signals.error.connect(self._on_scan_error)
        worker.signals.progress.connect(self.scan_progress.emit)
        QThreadPool.globalInstance().start(worker)

    def clear(self):
        """Clear all cached data."""
        with self._lock:
            self._tracks.clear()
            self._album_index.clear()
            self._album_only_index.clear()
            self._artist_index.clear()
            self._genre_index.clear()
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

    def _on_partial_result(self, batch: list[dict]):
        """Called with each incremental batch of tracks during scanning."""
        with self._lock:
            self._tracks.extend(batch)
            self._index_tracks(batch)
            self._is_ready = True  # Content available after first batch

        self.data_ready.emit()

    def _on_scan_complete(self, tracks: list[dict]):
        """Called when background scan finishes successfully."""
        with self._lock:
            self._is_loading = False
            self._worker = None

        # Save to disk cache for next launch
        self._save_disk_cache(self._music_folder, tracks)

        self.scan_finished.emit()
        self.data_ready.emit()

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

    def _load_disk_cache(self, music_folder: str) -> dict:
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
            logger.info("Loaded PC library cache: %d entries", len(result))
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
