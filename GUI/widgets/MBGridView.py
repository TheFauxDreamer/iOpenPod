import logging
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

    Caches widgets per category so tab switches are instant (no widget
    destruction/recreation).
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
        self.columnCount = 1
        self._current_category = "Albums"
        self._load_id = 0
        self._pending_items = None
        self._pending_index = 0
        self._pending_load_id = 0
        self._pending_category: str | None = None  # Category being built (for widget cache)
        self._reattach_index = 0
        self._reattach_load_id = 0

        # Expansion state
        self._expander = AlbumExpanderPanel(self)
        self._expander.close_requested.connect(self.collapseExpander)
        self._expander.track_play_requested.connect(self.track_play_requested.emit)
        self._expanded_item_index: int = -1  # Index in self.gridItems, -1 = collapsed
        self._cache = None  # Active cache reference for track lookups

        # Widget cache: category -> list of grid item widgets (Phase 3)
        self._widget_cache: dict[str, list[MusicBrowserGridItem]] = {}

    def loadCategory(self, category: str, cache=None):
        """Load and display items for the specified category."""
        log.debug(f"loadCategory() called: {category}")

        self._current_category = category

        if cache is None:
            from ..app import iTunesDBCache
            cache = iTunesDBCache.get_instance()

        self._cache = cache

        if not cache.is_ready():
            self.clearGrid()
            return

        # Check if we have cached widgets for this category
        if category in self._widget_cache:
            cached_widgets = self._widget_cache[category]
            if cached_widgets:
                log.debug(f"Reusing {len(cached_widgets)} cached widgets for {category}")
                self._detach_widgets()  # Remove current widgets from layout
                self.gridItems = cached_widgets
                self.columnCount = max(1, self._get_available_width() // _CELL_W)
                self._update_margins()
                # Batch the reattach to avoid freezing with 2000+ widgets
                self._load_id += 1
                self._reattach_index = 0
                self._reattach_load_id = self._load_id
                self._reattachBatch()
                return

        # No cached widgets — build fresh
        self._detach_widgets()
        self.gridItems = []

        # Use pre-computed item lists if available (PCLibraryCache),
        # fall back to build_*_list() for iTunesDBCache
        if category == "Albums":
            if hasattr(cache, 'get_album_items'):
                items = cache.get_album_items()
            else:
                from ..app import build_album_list
                items = build_album_list(cache)
        elif category == "Artists":
            if hasattr(cache, 'get_artist_items'):
                items = cache.get_artist_items()
            else:
                from ..app import build_artist_list
                items = build_artist_list(cache)
        elif category == "Genres":
            if hasattr(cache, 'get_genre_items'):
                items = cache.get_genre_items()
            else:
                from ..app import build_genre_list
                items = build_genre_list(cache)
        else:
            return

        self._pending_category = category
        self.populateGrid(items)

    # Number of widgets to create per batch before yielding to event loop
    _BATCH_SIZE = 40

    def populateGrid(self, items):
        """Populate the grid with items in batches to keep the UI responsive."""
        log.debug(f"populateGrid() called with {len(items)} items")
        self._detach_widgets()
        self.gridItems = []

        self._load_id += 1
        current_load_id = self._load_id

        self.columnCount = max(1, self._get_available_width() // _CELL_W)
        self._update_margins()

        if not items:
            return

        # Store items for batched creation
        self._pending_items = list(items)
        self._pending_index = 0
        self._pending_load_id = current_load_id
        self._processBatch()

    def _processBatch(self):
        """Create the next batch of grid item widgets."""
        if self._load_id != self._pending_load_id:
            # A newer load has started — abort this one
            return

        items = self._pending_items
        start = self._pending_index
        end = min(start + self._BATCH_SIZE, len(items))

        for i in range(start, end):
            item = items[i]
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
            self.gridLayout.setRowMinimumHeight(row, Metrics.GRID_ITEM_H)

        self._pending_index = end

        if end < len(items):
            # Schedule next batch — yields to event loop so UI stays responsive
            QTimer.singleShot(0, self._processBatch)
        else:
            # All done — store in widget cache and clean up
            if self._pending_category:
                self._widget_cache[self._pending_category] = list(self.gridItems)
                self._pending_category = None
            self._pending_items = None
            log.debug(f"populateGrid() finished: {len(self.gridItems)} widgets created")

    def _reattachBatch(self):
        """Re-add cached widgets to the layout in batches."""
        if self._load_id != self._reattach_load_id:
            return

        start = self._reattach_index
        end = min(start + self._BATCH_SIZE, len(self.gridItems))

        for i in range(start, end):
            grid_item = self.gridItems[i]
            row = i // self.columnCount
            col = i % self.columnCount
            self.gridLayout.addWidget(grid_item, row, col)
            self.gridLayout.setRowMinimumHeight(row, Metrics.GRID_ITEM_H)
            grid_item.show()

        self._reattach_index = end

        if end < len(self.gridItems):
            QTimer.singleShot(0, self._reattachBatch)
        else:
            log.debug(f"_reattachBatch() finished: {len(self.gridItems)} widgets reattached")

    def _detach_widgets(self):
        """Remove all grid items from layout without destroying them."""
        # Collapse expander
        self._expanded_item_index = -1
        self._expander.hide()
        self.gridLayout.removeWidget(self._expander)

        # Remove widgets from layout but keep them alive
        while self.gridLayout.count():
            item = self.gridLayout.takeAt(0)
            if item and item.widget():
                item.widget().hide()

        # Reset row minimum heights
        for r in range(self.gridLayout.rowCount()):
            self.gridLayout.setRowMinimumHeight(r, 0)

    def invalidateWidgetCache(self):
        """Destroy all cached widgets (call when data changes)."""
        log.debug("invalidateWidgetCache() — destroying all cached widgets")
        for category, widgets in self._widget_cache.items():
            for w in widgets:
                w.cleanup()
                w.deleteLater()
        self._widget_cache.clear()

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
        self._layout_with_expander(scroll=False)
        self._populate_expander(item_data)
        # Scroll after expander content is populated and has its final size
        QTimer.singleShot(100, self._scroll_to_expander)
        self.item_selected.emit(item_data)

    def _layout_with_expander(self, scroll: bool = True):
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

        if scroll:
            QTimer.singleShot(100, self._scroll_to_expander)

    def _scroll_to_expander(self):
        """Scroll so the clicked album card (and expander below it) is visible."""
        scroll = self.parent()
        if not scroll or not hasattr(scroll, 'ensureWidgetVisible'):
            return
        # Scroll to the clicked grid item so the card + expander are in view
        if 0 <= self._expanded_item_index < len(self.gridItems):
            scroll.ensureWidgetVisible(
                self.gridItems[self._expanded_item_index], 0, 50)
        else:
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
        elif category == "Genres":
            self._expand_genre(item_data, cache)
        else:
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

    def _expand_genre(self, item_data: dict, cache):
        """Expand to show a genre's tracks grouped by album."""
        genre = item_data.get("filter_value") or item_data.get("title", "")
        genre_index = cache.get_genre_index()
        all_tracks = genre_index.get(genre, [])

        if not all_tracks:
            return

        # Group tracks by album (same pattern as _expand_artist)
        albums: dict[str, list[dict]] = {}
        for track in all_tracks:
            album_name = track.get("Album", "Unknown Album")
            albums.setdefault(album_name, []).append(track)

        albums_with_tracks = []
        for album_name, tracks in sorted(albums.items()):
            year = next((t.get("year") for t in tracks if t.get("year")), None)
            album_data = {
                "title": album_name,
                "year": year,
            }
            albums_with_tracks.append((album_data, tracks))

        self._expander.show_artist(genre, albums_with_tracks)

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
            self.gridLayout.setRowMinimumHeight(row, Metrics.GRID_ITEM_H)

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
        """Clear all grid items and destroy widgets."""
        log.debug(f"clearGrid() called, current items: {len(self.gridItems)}, load_id: {self._load_id}")
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
        # Also invalidate widget cache since we're clearing
        self._widget_cache.clear()

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
