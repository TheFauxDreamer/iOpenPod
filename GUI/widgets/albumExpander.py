"""
AlbumExpanderPanel – iTunes 11 style inline expansion panel.

When the user clicks an album in the grid, this panel expands below
that grid row showing album art on the left and a track listing on the
right, with a dominant-color background extracted from the artwork.
"""

import logging
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QPixmap, QColor, QPainter, QPainterPath, QLinearGradient
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget,
    QSizePolicy, QGridLayout,
)

from ..styles import Colors, FONT_FAMILY, Metrics
from .formatters import format_duration_mmss, get_format_tag, get_album_format_tag

log = logging.getLogger(__name__)

# Panel dimensions
_ART_SIZE = 180
_PANEL_MIN_H = 200
_TRACK_ROW_H = 26


class AlbumExpanderPanel(QFrame):
    """Inline panel showing album details, inserted below a grid row."""

    close_requested = pyqtSignal()
    track_play_requested = pyqtSignal(dict, list)  # (track, queue)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_tracks: list[dict] = []
        self.setMinimumHeight(_PANEL_MIN_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._bg_color = (40, 40, 40)
        self._text_color = "rgba(255,255,255,230)"
        self._text_secondary_color = "rgba(255,255,255,150)"
        self._current_item_data: dict | None = None

        # Main layout: [art] [track list]
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(20, 16, 20, 16)
        self._layout.setSpacing(20)

        # Left: album art
        self._art_label = QLabel()
        self._art_label.setFixedSize(_ART_SIZE, _ART_SIZE)
        self._art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._art_label.setStyleSheet(f"""
            background: {Colors.SURFACE_HOVER};
            border-radius: {Metrics.BORDER_RADIUS}px;
            border: none;
        """)
        self._layout.addWidget(self._art_label, 0, Qt.AlignmentFlag.AlignTop)

        # Right: header + track list
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(4)

        # Album title
        self._title_label = QLabel()
        self._title_label.setFont(QFont(FONT_FAMILY, 14, QFont.Weight.Bold))
        self._title_label.setWordWrap(True)
        right.addWidget(self._title_label)

        # Artist + year subtitle
        self._subtitle_label = QLabel()
        self._subtitle_label.setFont(QFont(FONT_FAMILY, 11))
        right.addWidget(self._subtitle_label)

        right.addSpacing(8)

        # Track list container
        self._track_list = QVBoxLayout()
        self._track_list.setContentsMargins(0, 0, 0, 0)
        self._track_list.setSpacing(0)
        right.addLayout(self._track_list)

        right.addStretch()

        # Close button
        self._close_btn = QLabel("✕")
        self._close_btn.setFont(QFont(FONT_FAMILY, 14, QFont.Weight.Bold))
        self._close_btn.setFixedSize(28, 28)
        self._close_btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.mousePressEvent = lambda e: self.close_requested.emit()

        # Top-right close button layout
        right_with_close = QHBoxLayout()
        right_with_close.setContentsMargins(0, 0, 0, 0)
        right_with_close.addLayout(right, 1)
        right_with_close.addWidget(self._close_btn, 0, Qt.AlignmentFlag.AlignTop)

        self._layout.addLayout(right_with_close, 1)

        self.hide()

    def show_album(self, item_data: dict, tracks: list[dict],
                   artwork: QPixmap | None = None,
                   bg_color: tuple | None = None,
                   text_color: str | None = None,
                   text_secondary: str | None = None):
        """Populate the panel for a single album."""
        self._current_item_data = item_data
        self._current_tracks = list(tracks)

        # Set colours
        if bg_color:
            self._bg_color = bg_color
        if text_color:
            self._text_color = text_color
        if text_secondary:
            self._text_secondary_color = text_secondary

        self._apply_colors()

        # Title & subtitle
        title = item_data.get("title", "")
        artist = item_data.get("artist", "")
        year = item_data.get("year")
        self._title_label.setText(title)
        sub_parts = [artist]
        if year and year > 0:
            sub_parts.append(str(year))
        self._subtitle_label.setText(" · ".join(sub_parts))

        # Artwork
        if artwork and not artwork.isNull():
            scaled = artwork.scaled(
                _ART_SIZE, _ART_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._art_label.setPixmap(scaled)
            self._art_label.setStyleSheet(f"""
                border-radius: {Metrics.BORDER_RADIUS}px;
                border: none;
                background: transparent;
            """)
        else:
            self._art_label.clear()
            self._art_label.setText("♪")
            self._art_label.setFont(QFont(FONT_FAMILY, 48))
            self._art_label.setStyleSheet(f"""
                background: {Colors.SURFACE_HOVER};
                border-radius: {Metrics.BORDER_RADIUS}px;
                border: none;
                color: {self._text_secondary_color};
            """)

        # Build track rows
        self._clear_track_list()

        # Sort tracks by disc number then track number
        sorted_tracks = sorted(
            tracks,
            key=lambda t: (t.get("discNumber", 0), t.get("trackNumber", 0)),
        )

        # Show per-track format tags only when the album has mixed formats
        show_format = not get_album_format_tag(sorted_tracks)

        for track in sorted_tracks:
            row = self._make_track_row(track, show_format=show_format)
            self._track_list.addWidget(row)

        # Adjust height based on content
        track_height = len(sorted_tracks) * _TRACK_ROW_H + 60
        self.setMinimumHeight(max(_PANEL_MIN_H, _ART_SIZE + 32, track_height))

        self.show()

    def show_artist(self, artist: str, albums_with_tracks: list[tuple[dict, list[dict]]]):
        """Show artist view with tracks grouped by album."""
        self._current_item_data = {"title": artist, "category": "Artists"}
        # Flatten all tracks for the play queue
        self._current_tracks = [t for _, tracks in albums_with_tracks for t in tracks]

        # Use the first album's colors if available
        first_album = albums_with_tracks[0][0] if albums_with_tracks else {}
        bg = first_album.get("dominant_color")
        colors = first_album.get("album_colors", {})
        if bg:
            self._bg_color = bg
        if colors.get("text"):
            self._text_color = colors["text"]
        if colors.get("text_secondary"):
            self._text_secondary_color = colors["text_secondary"]
        self._apply_colors()

        self._title_label.setText(artist)
        self._subtitle_label.setText(
            f"{len(albums_with_tracks)} albums · "
            f"{sum(len(t) for _, t in albums_with_tracks)} songs"
        )

        # No single artwork for artist view
        self._art_label.clear()
        self._art_label.setText("♫")
        self._art_label.setFont(QFont(FONT_FAMILY, 48))
        self._art_label.setStyleSheet(f"""
            background: {Colors.SURFACE_HOVER};
            border-radius: {Metrics.BORDER_RADIUS}px;
            border: none;
            color: {self._text_secondary_color};
        """)

        self._clear_track_list()

        total_tracks = 0
        for album_data, tracks in albums_with_tracks:
            # Album sub-header
            album_header = QLabel(
                f"{album_data.get('title', 'Unknown Album')}"
                f" ({album_data.get('year', '')})"
                if album_data.get('year') else
                album_data.get('title', 'Unknown Album')
            )
            album_header.setFont(QFont(FONT_FAMILY, 11, QFont.Weight.DemiBold))
            album_header.setStyleSheet(f"""
                color: {self._text_color};
                padding: 8px 0 2px 0;
                background: transparent;
            """)
            self._track_list.addWidget(album_header)

            sorted_tracks = sorted(
                tracks,
                key=lambda t: (t.get("discNumber", 0), t.get("trackNumber", 0)),
            )
            show_format = not get_album_format_tag(sorted_tracks)
            for track in sorted_tracks:
                row = self._make_track_row(track, show_format=show_format)
                self._track_list.addWidget(row)
            total_tracks += len(sorted_tracks)

        track_height = total_tracks * _TRACK_ROW_H + len(albums_with_tracks) * 36 + 60
        self.setMinimumHeight(max(_PANEL_MIN_H, track_height))
        self.show()

    def current_item_data(self) -> dict | None:
        return self._current_item_data

    # ── Internal ───────────────────────────────────────────────

    def _apply_colors(self):
        r, g, b = self._bg_color
        # Slightly darker shade for gradient
        dr, dg, db = max(0, r - 30), max(0, g - 30), max(0, b - 30)
        self.setStyleSheet(f"""
            AlbumExpanderPanel {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgb({r},{g},{b}), stop:1 rgb({dr},{dg},{db}));
                border: none;
                border-radius: 0px;
            }}
        """)
        self._title_label.setStyleSheet(
            f"color: {self._text_color}; background: transparent;")
        self._subtitle_label.setStyleSheet(
            f"color: {self._text_secondary_color}; background: transparent;")
        self._close_btn.setStyleSheet(f"""
            color: {self._text_secondary_color};
            background: transparent;
            border: none;
            border-radius: 14px;
        """)

    def _make_track_row(self, track: dict, show_format: bool = False) -> QWidget:
        """Create a single track row widget."""
        row = QFrame()
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.setFixedHeight(_TRACK_ROW_H)
        # Click to play: emit signal with this track + all tracks in current view
        row.mousePressEvent = lambda e, t=track: self.track_play_requested.emit(
            t, self._current_tracks)
        row.setStyleSheet(f"""
            QFrame {{
                background: transparent;
                border: none;
                border-bottom: 1px solid rgba(255,255,255,15);
            }}
            QFrame:hover {{
                background: rgba(255,255,255,10);
            }}
        """)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(8)

        # Track number
        num = track.get("trackNumber", 0)
        num_label = QLabel(str(num) if num else "")
        num_label.setFixedWidth(24)
        num_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        num_label.setFont(QFont(FONT_FAMILY, 10))
        num_label.setStyleSheet(
            f"color: {self._text_secondary_color}; background: transparent; border: none;")
        layout.addWidget(num_label)

        # Title
        title_label = QLabel(track.get("Title", ""))
        title_label.setFont(QFont(FONT_FAMILY, 10))
        title_label.setStyleSheet(
            f"color: {self._text_color}; background: transparent; border: none;")
        layout.addWidget(title_label, 1)

        # Format tag (only shown for mixed-format albums)
        if show_format:
            fmt = get_format_tag(track)
            if fmt:
                fmt_label = QLabel(fmt)
                fmt_label.setFixedWidth(40)
                fmt_label.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                fmt_label.setFont(QFont(FONT_FAMILY, 8))
                fmt_label.setStyleSheet(
                    f"color: {self._text_secondary_color}; background: rgba(255,255,255,8);"
                    f" border: none; border-radius: 3px; padding: 1px 4px;")
                layout.addWidget(fmt_label)

        # Duration
        duration = track.get("length", 0)
        dur_label = QLabel(format_duration_mmss(duration))
        dur_label.setFixedWidth(50)
        dur_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        dur_label.setFont(QFont(FONT_FAMILY, 10))
        dur_label.setStyleSheet(
            f"color: {self._text_secondary_color}; background: transparent; border: none;")
        layout.addWidget(dur_label)

        return row

    def _clear_track_list(self):
        """Remove all track rows."""
        while self._track_list.count():
            item = self._track_list.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def paintEvent(self, event):
        """Custom paint for the upward-pointing triangle indicator."""
        super().paintEvent(event)
        # The triangle is drawn by the grid view based on the clicked item's position
