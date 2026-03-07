import logging
from collections import deque
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QGridLayout, QSizePolicy
from .MBGridViewItem import MusicBrowserGridItem
from .albumExpander import AlbumExpanderPanel
from ..styles import Metrics

log = logging.getLogger(__name__)

# Grid calculation constants
_CELL_W = Metrics.GRID_ITEM_W + Metrics.GRID_SPACING


class MusicBrowserGrid(QFrame):
    """Grid view that displays albums, artists, or genres as clickable items.

    Supports iTunes 11 style inline expansion: clicking an item inserts
    an AlbumExpanderPanel below that row.
    """
    item_selected = pyqtSignal(dict)  # Emits when an item is clicked
    track_play_requested = pyqtSignal(dict, list)  # Relayed from expander

    def __init__(self):
        super().__init__()
        self.gridLayout = QGridLayout(self)
        self.gridLayout.setContentsMargins(Metrics.GRID_SPACING, Metrics.GRID_SPACING,
                                           Metrics.GRID_SPACING, Metrics.GRID_SPACING)
        self.gridLayout.setSpacing(Metrics.GRID_SPACING)
        self.gridLayout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Allow the widget to shrink below the layout's natural minimum.
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.gridItems: list[MusicBrowserGridItem] = []
        self.pendingItems: deque = deque()
        self.timerActive = False
        self.columnCount = 1
        self._current_category = "Albums"
        self._load_id = 0

        # Expansion state
        self._expander = AlbumExpanderPanel(self)
        self._expander.close_requested.connect(self.collapseExpander)
        self._expander.track_play_requested.connect(self.track_play_requested.emit)
        self._expanded_item_index: int = -1  # Index in self.gridItems, -1 = collapsed
        self._cache = None  # Active cache reference for track lookups

    def loadCategory(self, category: str, cache=None):
        """Load and display items for the specified category."""
        from ..app import build_album_list, build_artist_list, build_genre_list
        log.debug(f"loadCategory() called: {category}")

        self._current_category = category
        self.clearGrid()

        if cache is None:
            from ..app import iTunesDBCache
            cache = iTunesDBCache.get_instance()

        self._cache = cache

        if not cache.is_ready():
            return

        if category == "Albums":
            items = build_album_list(cache)
        elif category == "Artists":
            items = build_artist_list(cache)
        elif category == "Genres":
            items = build_genre_list(cache)
        else:
            return

        self.populateGrid(items)

    def populateGrid(self, items):
        """Populate the grid with items."""
        log.debug(f"populateGrid() called with {len(items)} items")
        self.clearGrid()

        self._load_id += 1
        current_load_id = self._load_id

        self.columnCount = max(1, self._get_available_width() // _CELL_W)
        self._update_margins()

        self.pendingItems = deque(enumerate(items))

        # Pre-set all row heights so the layout doesn't shift as batches load
        total_rows = (len(items) + self.columnCount - 1) // self.columnCount
        for r in range(total_rows):
            self.gridLayout.setRowMinimumHeight(r, Metrics.GRID_ITEM_H)

        if self.pendingItems and not self.timerActive:
            self.timerActive = True
            self._startAddingItems(current_load_id)

    def _startAddingItems(self, load_id: int):
        self._addNextItem(load_id)

    def _addNextItem(self, load_id: int):
        if load_id != self._load_id:
            self.timerActive = False
            return
        if not self.pendingItems:
            self.timerActive = False
            return

        batch_size = 5
        for _ in range(batch_size):
            if not self.pendingItems:
                break

            i, item = self.pendingItems.popleft()
            row = i // self.columnCount
            col = i % self.columnCount

            if isinstance(item, dict):
                title = item.get("title") or item.get("album", "Unknown")
                subtitle = item.get("subtitle") or item.get("artist", "")
                mhiiLink = item.get("mhiiLink")

                item_data = {
                    "title": title,
                    "subtitle": subtitle,
                    "mhiiLink": mhiiLink,
                    "_pc_art_hash": item.get("_pc_art_hash"),
                    "category": item.get("category", "Albums"),
                    "filter_key": item.get("filter_key", "Album"),
                    "filter_value": item.get("filter_value", title),
                    "album": item.get("album"),
                    "artist": item.get("artist"),
                    "year": item.get("year"),
                    "track_count": item.get("track_count"),
                    "total_length_ms": item.get("total_length_ms"),
                }

                gridItem = MusicBrowserGridItem(title, subtitle, mhiiLink, item_data)
                gridItem.clicked.connect(self._onItemClicked)
                self.gridItems.append(gridItem)
            elif isinstance(item, MusicBrowserGridItem):
                gridItem = item
                gridItem.clicked.connect(self._onItemClicked)
            else:
                continue

            self.gridLayout.addWidget(gridItem, row, col)

        if self.pendingItems and load_id == self._load_id:
            QTimer.singleShot(8, lambda: self._addNextItem(load_id))
        else:
            self.timerActive = False

    def _onItemClicked(self, item_data: dict):
        """Handle grid item click — toggle inline expansion."""
        # Find the index of the clicked item
        clicked_index = -1
        for i, grid_item in enumerate(self.gridItems):
            if grid_item.item_data is item_data:
                clicked_index = i
                break

        if clicked_index < 0:
            # Fallback: match by title
            title = item_data.get("title", "")
            for i, grid_item in enumerate(self.gridItems):
                if grid_item.item_data.get("title") == title:
                    clicked_index = i
                    break

        if clicked_index < 0:
            self.item_selected.emit(item_data)
            return

        # Toggle: if same item clicked again, collapse
        if clicked_index == self._expanded_item_index:
            self.collapseExpander()
            return

        # Expand for the new item
        self._expanded_item_index = clicked_index
        self._layout_with_expander()
        self._populate_expander(item_data)
        self.item_selected.emit(item_data)

    def _layout_with_expander(self):
        """Re-layout all grid items, inserting the expander after the clicked item's row."""
        if self._expanded_item_index < 0:
            return

        clicked_row = self._expanded_item_index // self.columnCount
        expander_row = clicked_row + 1  # The row the expander occupies

        # Remove expander from layout if it's there
        self.gridLayout.removeWidget(self._expander)

        # Re-position all grid items, shifting items below the expander row down by 1
        for i, grid_item in enumerate(self.gridItems):
            item_row = i // self.columnCount
            col = i % self.columnCount
            # Items at or above the clicked row stay in place
            if item_row <= clicked_row:
                actual_row = item_row
            else:
                # Items below get shifted down by 1 to make room for expander
                actual_row = item_row + 1
            self.gridLayout.addWidget(grid_item, actual_row, col)

        # Insert expander spanning all columns
        self.gridLayout.addWidget(
            self._expander, expander_row, 0, 1, self.columnCount)
        self._expander.show()

        # Scroll to make the expander visible
        QTimer.singleShot(50, self._scroll_to_expander)

    def _scroll_to_expander(self):
        """Scroll the parent QScrollArea to make the expander visible."""
        scroll = self.parent()
        if scroll and hasattr(scroll, 'ensureWidgetVisible'):
            scroll.ensureWidgetVisible(self._expander, 0, 50)

    def _populate_expander(self, item_data: dict):
        """Fill the expander panel with data for the clicked item."""
        category = item_data.get("category", "Albums")
        cache = self._cache

        if not cache or not cache.is_ready():
            return

        if category == "Albums":
            self._expand_album(item_data, cache)
        elif category == "Artists":
            self._expand_artist(item_data, cache)
        else:
            # Genres or other — just show tracks
            self._expand_album(item_data, cache)

    def _expand_album(self, item_data: dict, cache):
        """Expand to show an album's tracks."""
        # Get tracks for this album
        album = item_data.get("filter_value") or item_data.get("album") or item_data.get("title", "")
        artist = item_data.get("artist", "")

        album_index = cache.get_album_index()
        album_only_index = cache.get_album_only_index()

        tracks = album_index.get((album, artist), [])
        if not tracks:
            tracks = album_only_index.get(album, [])

        # Get artwork and colors from the grid item
        dominant_color = item_data.get("dominant_color", (60, 60, 60))
        album_colors = item_data.get("album_colors", {})
        raw_text = album_colors.get("text")
        raw_sec = album_colors.get("text_secondary")
        # Convert RGB tuples to CSS strings; fall back to white on dark
        text = (f"rgb({raw_text[0]},{raw_text[1]},{raw_text[2]})"
                if isinstance(raw_text, (tuple, list)) else
                raw_text or "rgba(255,255,255,230)")
        text_sec = (f"rgb({raw_sec[0]},{raw_sec[1]},{raw_sec[2]})"
                    if isinstance(raw_sec, (tuple, list)) else
                    raw_sec or "rgba(255,255,255,150)")

        # Get the pixmap from the grid item's label if available
        artwork = None
        for grid_item in self.gridItems:
            if grid_item.item_data is item_data:
                pm = grid_item.img_label.pixmap()
                if pm and not pm.isNull():
                    artwork = pm
                break

        self._expander.show_album(
            item_data, tracks,
            artwork=artwork,
            bg_color=dominant_color,
            text_color=text,
            text_secondary=text_sec,
        )

    def _expand_artist(self, item_data: dict, cache):
        """Expand to show an artist's tracks grouped by album."""
        artist = item_data.get("filter_value") or item_data.get("title", "")
        artist_index = cache.get_artist_index()
        all_tracks = artist_index.get(artist, [])

        if not all_tracks:
            return

        # Group tracks by album
        albums: dict[str, list[dict]] = {}
        for track in all_tracks:
            album_name = track.get("Album", "Unknown Album")
            albums.setdefault(album_name, []).append(track)

        # Build albums_with_tracks list
        albums_with_tracks = []
        for album_name, tracks in sorted(albums.items()):
            year = next((t.get("year") for t in tracks if t.get("year")), None)
            album_data = {
                "title": album_name,
                "year": year,
            }
            albums_with_tracks.append((album_data, tracks))

        self._expander.show_artist(artist, albums_with_tracks)

    def collapseExpander(self):
        """Collapse the expansion panel."""
        if self._expanded_item_index < 0:
            return

        self._expanded_item_index = -1
        self._expander.hide()
        self.gridLayout.removeWidget(self._expander)

        # Re-layout items without the gap
        self._update_margins()
        for i, grid_item in enumerate(self.gridItems):
            row = i // self.columnCount
            col = i % self.columnCount
            self.gridLayout.addWidget(grid_item, row, col)

    def _get_available_width(self) -> int:
        parent = self.parent()
        if parent and hasattr(parent, 'width'):
            return parent.width()
        return self.width()

    def _update_margins(self):
        available = self._get_available_width()
        used = self.columnCount * Metrics.GRID_ITEM_W + max(0, self.columnCount - 1) * Metrics.GRID_SPACING
        leftover = max(0, available - used)
        side = leftover // 2
        self.gridLayout.setContentsMargins(side, Metrics.GRID_SPACING, side, Metrics.GRID_SPACING)

    def rearrangeGrid(self):
        """Rearrange grid items based on the new column count."""
        if not self.gridItems:
            return

        self.columnCount = max(1, self._get_available_width() // _CELL_W)
        self._update_margins()

        if self._expanded_item_index >= 0:
            # Re-layout with expander in the right position
            self._layout_with_expander()
        else:
            for i, gridItem in enumerate(self.gridItems):
                row = i // self.columnCount
                col = i % self.columnCount
                self.gridLayout.addWidget(gridItem, row, col)
                self.gridLayout.setRowMinimumHeight(row, Metrics.GRID_ITEM_H)

    def clearGrid(self):
        """Clear all grid items to prepare for reloading."""
        log.debug(f"clearGrid() called, current items: {len(self.gridItems)}, load_id: {self._load_id}")
        self.timerActive = False
        self.pendingItems = deque()
        self._load_id += 1

        # Collapse expander
        self._expanded_item_index = -1
        self._expander.hide()
        self.gridLayout.removeWidget(self._expander)

        # Remove all widgets from layout
        while self.gridLayout.count():
            item = self.gridLayout.takeAt(0)
            if item:
                widget = item.widget()
                if widget and widget is not self._expander:
                    if isinstance(widget, MusicBrowserGridItem):
                        widget.cleanup()
                    widget.deleteLater()

        self.gridItems = []

        # Reset row minimum heights from previous load
        for r in range(self.gridLayout.rowCount()):
            self.gridLayout.setRowMinimumHeight(r, 0)

    def resizeEvent(self, a0):
        newCols = max(1, self._get_available_width() // _CELL_W)
        if self.columnCount != newCols:
            self.rearrangeGrid()
        else:
            self._update_margins()
        super().resizeEvent(a0)
