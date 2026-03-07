"""
MusicBrowser – main content area with a category tab bar and view stack.

Supports two data sources (switched via setDataSource):
  - "ipod" : reads from iTunesDBCache (default, current behaviour)
  - "library" : reads from PCLibraryCache (local PC music folder)
"""

import logging
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtWidgets import (
    QScrollArea, QFrame, QVBoxLayout, QSizePolicy, QStackedWidget, QLabel,
)
from PyQt6.QtGui import QFont

from .categoryTabBar import CategoryTabBar
from .MBGridView import MusicBrowserGrid
from .MBListView import MusicBrowserList
from .playlistBrowser import PlaylistBrowser
from ..styles import Colors, FONT_FAMILY

log = logging.getLogger(__name__)


class MusicBrowser(QFrame):
    """Main content area: tab bar + scrollable grid / track list / playlist views."""

    def __init__(self):
        super().__init__()
        self._current_category = "Albums"
        self._data_source = "ipod"  # "ipod" or "library"

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.mainLayout.setSpacing(0)

        # ── Tab bar ────────────────────────────────────────────
        self.tabBar = CategoryTabBar()
        self.tabBar.category_changed.connect(self._onTabChanged)
        self.mainLayout.addWidget(self.tabBar)

        # ── Content stack ──────────────────────────────────────
        self.stack = QStackedWidget()
        self.mainLayout.addWidget(self.stack)

        # Index 0: Grid view (Albums / Artists / Genres) inside a scroll area
        self.browserGrid = MusicBrowserGrid()
        self.browserGrid.item_selected.connect(self._onGridItemSelected)

        self.browserGridScroll = QScrollArea()
        self.browserGridScroll.setWidgetResizable(True)
        self.browserGridScroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.browserGridScroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.browserGridScroll.setMinimumHeight(0)
        self.browserGridScroll.setMinimumWidth(0)
        self.browserGridScroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.browserGridScroll.minimumSizeHint = lambda: QSize(0, 0)
        self.browserGridScroll.setWidget(self.browserGrid)
        self.browserGridScroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
        """)
        self.stack.addWidget(self.browserGridScroll)  # index 0

        # Index 1: Songs / track list (full-height, no grid)
        self.browserTrack = MusicBrowserList()
        self.browserTrack.setMinimumHeight(0)
        self.browserTrack.setMinimumWidth(0)
        self.browserTrack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.browserTrack.minimumSizeHint = lambda: QSize(0, 0)
        self.stack.addWidget(self.browserTrack)  # index 1

        # Index 2: Playlist browser
        self.playlistBrowser = PlaylistBrowser()
        self.stack.addWidget(self.playlistBrowser)  # index 2

        # Index 3: Empty state (no music folder / no iPod)
        self._emptyState = self._build_empty_state()
        self.stack.addWidget(self._emptyState)  # index 3

        # Debounce timer for data_ready signals during scanning
        self._data_ready_timer = QTimer(self)
        self._data_ready_timer.setSingleShot(True)
        self._data_ready_timer.setInterval(500)  # Coalesce updates within 500ms
        self._data_ready_timer.timeout.connect(self._refreshCurrentCategory)

        # Connect to theme changes
        from ..theme import ThemeManager
        ThemeManager.instance().theme_changed.connect(self._rebuild_styles)

    # ── Data source switching ──────────────────────────────────

    def setDataSource(self, source: str):
        """Switch between 'ipod' and 'library' data sources."""
        if source not in ("ipod", "library"):
            return
        if source == self._data_source:
            return
        self._data_source = source
        self._refreshCurrentCategory()

    def dataSource(self) -> str:
        return self._data_source

    # ── Public API ─────────────────────────────────────────────

    def reloadData(self):
        """Clear all views and wait for new data."""
        self.browserGrid.clearGrid()
        self.browserTrack.clearTable()
        self.playlistBrowser.clear()

    def onDataReady(self, force: bool = False):
        """Called when the active cache has new data (may fire many times during scan).

        During an active scan, only updates the progress message. The full
        grid rebuild happens once when the scan finishes (force=True) or
        when the debounce timer expires after scan completion.
        """
        cache = self._get_cache()
        if cache and cache.is_loading() and not force:
            # Scan still in progress — show progress count, don't rebuild grid
            track_count = len(cache.get_tracks()) if hasattr(cache, 'get_tracks') else 0
            if track_count > 0:
                self._show_empty(f"Scanning your music library... ({track_count:,} tracks found)")
            return
        # Data changed — invalidate cached grid widgets so they rebuild
        self.browserGrid.invalidateWidgetCache()
        # Scan finished or force — debounce the grid rebuild
        self._data_ready_timer.start()

    def updateCategory(self, category: str):
        """Programmatically switch category (used by sidebar in old flow)."""
        log.debug("updateCategory() called: %s", category)
        # Sidebar uses "Tracks"; tab bar uses "Songs"
        self._current_category = category
        tab_name = "Songs" if category == "Tracks" else category
        self.tabBar.setActiveCategory(tab_name)
        self._refreshCurrentCategory()

    # ── Internal ───────────────────────────────────────────────

    def _onTabChanged(self, category: str):
        """Handle tab bar click."""
        # Map "Songs" tab label to internal category name
        internal = "Tracks" if category == "Songs" else category
        self._current_category = internal
        self._refreshCurrentCategory()

    def _refreshCurrentCategory(self):
        """Load the appropriate view for the current category + data source."""
        log.debug("_refreshCurrentCategory: %s (source=%s)",
                  self._current_category, self._data_source)

        cache = self._get_cache()
        if cache is None or not cache.is_ready():
            # Show empty state if no data available
            if self._data_source == "library":
                if cache and cache.is_loading():
                    self._show_empty("Scanning your music library...")
                else:
                    from ..settings import get_settings
                    if get_settings().music_folder:
                        self._show_empty("Scanning your music library...")
                    else:
                        self._show_empty("Set your music folder in Settings to browse your library.")
            else:
                self._show_empty("Connect an iPod to browse its music.")
            return

        category = self._current_category

        if category == "Tracks":
            self.stack.setCurrentIndex(1)
            self.browserTrack.clearTable()
            self.browserTrack.clearFilter()
            self.browserTrack.resetDominantColor()
            self.browserTrack.loadTracks(cache=cache)
        elif category == "Playlists":
            self.stack.setCurrentIndex(2)
            self.playlistBrowser.loadPlaylists()
        else:
            # Albums, Artists, Genres → grid view
            self.stack.setCurrentIndex(0)
            self.browserGrid.loadCategory(category, cache=cache)

    def _onGridItemSelected(self, item_data: dict):
        """Handle grid item click — will trigger inline expansion in Phase 3."""
        log.debug("_onGridItemSelected: %s", item_data.get("title", "?"))
        # Phase 3 will add the inline album expansion here.
        # For now, this is a no-op placeholder.

    def _get_cache(self):
        """Return the active cache object based on the current data source."""
        if self._data_source == "library":
            from ..pc_library_cache import PCLibraryCache
            return PCLibraryCache.get_instance()
        else:
            from ..app import iTunesDBCache
            return iTunesDBCache.get_instance()

    def _show_empty(self, message: str):
        """Show the empty state with a message."""
        self._emptyLabel.setText(message)
        self.stack.setCurrentIndex(3)

    def _build_empty_state(self) -> QFrame:
        """Build a centered empty-state placeholder."""
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._emptyLabel = QLabel("")
        self._emptyLabel.setFont(QFont(FONT_FAMILY, 12))
        self._emptyLabel.setStyleSheet(f"color: {Colors.TEXT_TERTIARY};")
        self._emptyLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._emptyLabel.setWordWrap(True)
        layout.addWidget(self._emptyLabel)
        return frame

    def _rebuild_styles(self):
        """Rebuild theme-sensitive inline styles."""
        self._emptyLabel.setStyleSheet(f"color: {Colors.TEXT_TERTIARY};")
