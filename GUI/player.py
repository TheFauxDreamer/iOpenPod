"""
AudioPlayer – singleton playback engine wrapping QMediaPlayer + QAudioOutput.

Manages a play queue, track path resolution (PC and iPod), auto-advance,
and exposes signals for the mini player UI.
"""

import logging
import os
import sys

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

log = logging.getLogger(__name__)


def _resolve_track_path(track: dict) -> str | None:
    """Return the absolute filesystem path for a track dict, or None."""
    # PC library tracks have an absolute path
    pc_path = track.get("_pc_path")
    if pc_path and os.path.exists(pc_path):
        return pc_path

    # iPod tracks store a colon-separated relative path in "Location"
    location = track.get("Location")
    if location:
        from .app import DeviceManager
        device = DeviceManager.get_instance()
        if device.device_path:
            relative = location.replace(":", "/").lstrip("/")
            full = os.path.join(device.device_path, relative)
            if os.path.exists(full):
                return full

    return None


class AudioPlayer(QObject):
    """Singleton audio player with queue management."""

    # ── Signals ───────────────────────────────────────────────
    track_changed = pyqtSignal(dict)    # emitted when current track changes
    state_changed = pyqtSignal(str)     # "playing" | "paused" | "stopped"
    position_changed = pyqtSignal(int)  # current position in ms
    duration_changed = pyqtSignal(int)  # total duration in ms

    _instance: "AudioPlayer | None" = None

    @classmethod
    def get_instance(cls) -> "AudioPlayer":
        if cls._instance is None:
            cls._instance = AudioPlayer()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._queue: list[dict] = []
        self._current_index: int = -1

        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        self._audio_output.setVolume(0.8)

        # Forward QMediaPlayer signals
        self._player.positionChanged.connect(self.position_changed.emit)
        self._player.durationChanged.connect(self.duration_changed.emit)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_error)

        # Hardware media key support
        self._media_key_monitor = None
        self._setup_media_keys()

    # ── Public API ────────────────────────────────────────────

    def play_track(self, track: dict, queue: list[dict] | None = None):
        """Play a single track. Optionally set the full queue."""
        if queue is not None:
            self._queue = list(queue)
            try:
                self._current_index = self._queue.index(track)
            except ValueError:
                self._queue = [track]
                self._current_index = 0
        else:
            self._queue = [track]
            self._current_index = 0
        self._play_current()

    def play_tracks(self, tracks: list[dict], start_index: int = 0):
        """Set queue and start playing at the given index."""
        if not tracks:
            return
        self._queue = list(tracks)
        self._current_index = max(0, min(start_index, len(tracks) - 1))
        self._play_current()

    def toggle_play_pause(self):
        """Toggle between playing and paused states."""
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._player.play()
        elif self._queue and self._current_index >= 0:
            self._play_current()

    def next_track(self):
        """Advance to the next track in the queue."""
        if not self._queue:
            return
        if self._current_index < len(self._queue) - 1:
            self._current_index += 1
            self._play_current()
        else:
            # End of queue
            self._player.stop()
            self.state_changed.emit("stopped")

    def prev_track(self):
        """Go to the previous track, or restart current if past 3 seconds."""
        if not self._queue:
            return
        # If past 3 seconds, restart current track
        if self._player.position() > 3000:
            self._player.setPosition(0)
            return
        if self._current_index > 0:
            self._current_index -= 1
            self._play_current()

    def seek(self, ms: int):
        """Seek to position in milliseconds."""
        self._player.setPosition(ms)

    def set_volume(self, volume: float):
        """Set volume (0.0 to 1.0)."""
        self._audio_output.setVolume(max(0.0, min(1.0, volume)))

    def volume(self) -> float:
        return self._audio_output.volume()

    def current_track(self) -> dict | None:
        """Return the currently playing track dict, or None."""
        if 0 <= self._current_index < len(self._queue):
            return self._queue[self._current_index]
        return None

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def queue(self) -> list[dict]:
        return list(self._queue)

    def current_index(self) -> int:
        return self._current_index

    # ── Internal ──────────────────────────────────────────────

    def _play_current(self):
        """Load and play the track at _current_index."""
        if not (0 <= self._current_index < len(self._queue)):
            return

        track = self._queue[self._current_index]
        path = _resolve_track_path(track)
        if not path:
            log.warning("Cannot resolve path for track: %s", track.get("Title", "?"))
            # Try next track instead of silently failing
            if self._current_index < len(self._queue) - 1:
                self._current_index += 1
                self._play_current()
            return

        log.info("Playing: %s", path)
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()
        self.track_changed.emit(track)

    def _on_state_changed(self, state: QMediaPlayer.PlaybackState):
        """Map QMediaPlayer states to simple string signals."""
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.state_changed.emit("playing")
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self.state_changed.emit("paused")
        else:
            self.state_changed.emit("stopped")

    def _on_media_status(self, status: QMediaPlayer.MediaStatus):
        """Auto-advance when current track finishes."""
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.next_track()

    def _on_error(self, error, message=""):
        """Log playback errors."""
        log.error("Playback error (%s): %s", error, message)

    # ── Media Key Support ─────────────────────────────────────

    def _setup_media_keys(self):
        """Register for hardware media key events (macOS via PyObjC)."""
        if sys.platform != "darwin":
            return
        try:
            import AppKit
            import Quartz

            # Media key constants (NX_KEYTYPE_*)
            NX_KEYTYPE_PLAY = 16
            NX_KEYTYPE_NEXT = 17
            NX_KEYTYPE_PREVIOUS = 18
            NX_KEYTYPE_FAST = 19
            NX_KEYTYPE_REWIND = 20

            def _handle_media_key(event):
                """Handle system-defined events for media keys."""
                if event.type() != AppKit.NSEventTypeSystemDefined:
                    return event
                if event.subtype() != 8:  # 8 = media key subtype
                    return event

                data = event.data1()
                key_code = (data & 0xFFFF0000) >> 16
                key_state = (data & 0xFF00) >> 8  # 0xA = down, 0xB = up

                if key_state != 0x0A:  # Only handle key-down
                    return event

                if key_code == NX_KEYTYPE_PLAY:
                    self.toggle_play_pause()
                    return None  # Consume the event
                elif key_code in (NX_KEYTYPE_NEXT, NX_KEYTYPE_FAST):
                    self.next_track()
                    return None
                elif key_code in (NX_KEYTYPE_PREVIOUS, NX_KEYTYPE_REWIND):
                    self.prev_track()
                    return None

                return event

            # Register local event monitor for media keys
            mask = AppKit.NSEventMaskSystemDefined
            self._media_key_monitor = AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                mask, _handle_media_key
            )
            log.info("macOS media key support enabled")

        except ImportError:
            log.debug("PyObjC not available — media key support disabled")
        except Exception as e:
            log.warning("Failed to set up media keys: %s", e)
