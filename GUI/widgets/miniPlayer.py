"""
MiniPlayer – persistent playback bar at the bottom of the main window.

Shows track info, artwork, play/pause/prev/next controls, seek bar,
and volume slider.  Hidden when nothing is playing.
"""

import logging
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QPixmap, QIcon, QImage, QColor
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QSlider, QSizePolicy, QWidget,
)

from ..styles import Colors, FONT_FAMILY, Metrics
from .formatters import format_duration_mmss
from .scrollingLabel import ScrollingLabel

log = logging.getLogger(__name__)

_ART_SIZE = 48
_PLAYER_HEIGHT = 64

# ── SVG transport icons (24x24 viewBox) ──────────────────────
_SVG_PREV = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="4" width="3" height="16" fill="{c}"/><polygon points="20,3 8,12 20,21" fill="{c}"/></svg>'
_SVG_PLAY = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><polygon points="6,3 20,12 6,21" fill="{c}"/></svg>'
_SVG_PAUSE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="5" y="3" width="4" height="18" fill="{c}"/><rect x="15" y="3" width="4" height="18" fill="{c}"/></svg>'
_SVG_NEXT = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><polygon points="4,3 16,12 4,21" fill="{c}"/><rect x="18" y="4" width="3" height="16" fill="{c}"/></svg>'


def _color_to_hex(color_str: str) -> str:
    """Convert a Colors.* value (rgba or hex) to #rrggbb for SVG fill."""
    if color_str.startswith("#"):
        return color_str
    import re
    m = re.match(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', color_str)
    if m:
        return "#{:02x}{:02x}{:02x}".format(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return "#ffffff"


def _svg_icon(svg_template: str, color: str, size: int = 24) -> QIcon:
    """Render an SVG template with the given fill color to a QIcon."""
    svg_data = svg_template.format(c=color).encode("utf-8")
    img = QImage.fromData(svg_data, "SVG")
    if img.isNull():
        return QIcon()
    pix = QPixmap.fromImage(img).scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return QIcon(pix)


class MiniPlayer(QFrame):
    """Bottom bar mini player widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(_PLAYER_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._current_track: dict | None = None
        self._seeking = False  # True while user is dragging the seek slider

        self._build_ui()
        self._apply_styles()
        self.hide()

        # Connect to theme changes
        from ..theme import ThemeManager
        ThemeManager.instance().theme_changed.connect(self._apply_styles)

    def connect_player(self, player):
        """Wire up to an AudioPlayer instance."""
        player.track_changed.connect(self._on_track_changed)
        player.state_changed.connect(self._on_state_changed)
        player.position_changed.connect(self._on_position_changed)
        player.duration_changed.connect(self._on_duration_changed)

        self._player = player
        self._play_btn.clicked.connect(player.toggle_play_pause)
        self._prev_btn.clicked.connect(player.prev_track)
        self._next_btn.clicked.connect(player.next_track)
        self._seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self._seek_slider.sliderReleased.connect(self._on_seek_released)
        self._vol_slider.valueChanged.connect(
            lambda v: player.set_volume(v / 100.0))
        self._vol_slider.setValue(int(player.volume() * 100))

    # ── UI Construction ───────────────────────────────────────

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(12)

        # ── Left: artwork + track info ──
        self._art_label = QLabel()
        self._art_label.setFixedSize(_ART_SIZE, _ART_SIZE)
        self._art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._art_label.setStyleSheet(
            f"border-radius: {Metrics.BORDER_RADIUS_SM}px; border: none;")
        layout.addWidget(self._art_label)

        info_col = QVBoxLayout()
        info_col.setContentsMargins(0, 0, 0, 0)
        info_col.setSpacing(0)

        self._title_label = ScrollingLabel("\u2014")
        self._title_label.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.DemiBold))
        self._title_label.setFixedHeight(18)
        self._title_label.setAutoScroll(True)
        info_col.addWidget(self._title_label)

        self._artist_label = ScrollingLabel("")
        self._artist_label.setFont(QFont(FONT_FAMILY, 9))
        self._artist_label.setFixedHeight(16)
        self._artist_label.setAutoScroll(True)
        info_col.addWidget(self._artist_label)

        self._album_label = ScrollingLabel("")
        self._album_label.setFont(QFont(FONT_FAMILY, 9))
        self._album_label.setFixedHeight(16)
        self._album_label.setAutoScroll(True)
        info_col.addWidget(self._album_label)

        info_widget = QWidget()
        info_widget.setLayout(info_col)
        info_widget.setFixedWidth(200)
        layout.addWidget(info_widget)

        # ── Center: controls + seek bar ──
        center_col = QVBoxLayout()
        center_col.setContentsMargins(0, 6, 0, 6)
        center_col.setSpacing(2)

        # Transport buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._prev_btn = QPushButton()
        self._play_btn = QPushButton()
        self._next_btn = QPushButton()

        for btn in (self._prev_btn, self._play_btn, self._next_btn):
            btn.setFixedSize(32, 32)
            btn.setIconSize(QSize(18, 18))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_row.addWidget(btn)

        self._is_playing = False
        self._update_transport_icons()

        center_col.addLayout(btn_row)

        # Seek bar row
        seek_row = QHBoxLayout()
        seek_row.setSpacing(6)

        self._pos_label = QLabel("0:00")
        self._pos_label.setFont(QFont(FONT_FAMILY, 8))
        self._pos_label.setFixedWidth(38)
        self._pos_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        seek_row.addWidget(self._pos_label)

        self._seek_slider = QSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setRange(0, 0)
        seek_row.addWidget(self._seek_slider, 1)

        self._dur_label = QLabel("0:00")
        self._dur_label.setFont(QFont(FONT_FAMILY, 8))
        self._dur_label.setFixedWidth(38)
        self._dur_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        seek_row.addWidget(self._dur_label)

        center_col.addLayout(seek_row)

        center_widget = QWidget()
        center_widget.setLayout(center_col)
        center_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(center_widget, 1)

        # ── Right: volume ──
        vol_row = QHBoxLayout()
        vol_row.setSpacing(4)

        vol_icon = QLabel("\u266B")
        vol_icon.setFont(QFont(FONT_FAMILY, 10))
        vol_row.addWidget(vol_icon)

        self._vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(80)
        self._vol_slider.setFixedWidth(80)
        vol_row.addWidget(self._vol_slider)

        vol_widget = QWidget()
        vol_widget.setLayout(vol_row)
        layout.addWidget(vol_widget)

    # ── Styling ───────────────────────────────────────────────

    def _apply_styles(self):
        self.setStyleSheet(f"""
            MiniPlayer {{
                background: {Colors.SURFACE_ALT};
                border-top: 1px solid {Colors.BORDER_SUBTLE};
            }}
        """)
        self._title_label.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;")
        self._artist_label.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        self._album_label.setStyleSheet(
            f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none;")
        self._pos_label.setStyleSheet(
            f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none;")
        self._dur_label.setStyleSheet(
            f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none;")

        btn_style = f"""
            QPushButton {{
                background: transparent;
                color: {Colors.TEXT_PRIMARY};
                border: none;
                border-radius: 16px;
            }}
            QPushButton:hover {{
                background: {Colors.SURFACE_HOVER};
            }}
            QPushButton:pressed {{
                background: {Colors.ACCENT_DIM};
            }}
        """
        for btn in (self._prev_btn, self._play_btn, self._next_btn):
            btn.setStyleSheet(btn_style)

        slider_style = f"""
            QSlider::groove:horizontal {{
                height: 4px;
                background: {Colors.BORDER_SUBTLE};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 12px;
                height: 12px;
                margin: -4px 0;
                background: {Colors.TEXT_PRIMARY};
                border-radius: 6px;
            }}
            QSlider::sub-page:horizontal {{
                background: {Colors.ACCENT};
                border-radius: 2px;
            }}
        """
        self._seek_slider.setStyleSheet(slider_style)
        self._vol_slider.setStyleSheet(slider_style)

        self._art_label.setStyleSheet(f"""
            background: {Colors.SURFACE_HOVER};
            border-radius: {Metrics.BORDER_RADIUS_SM}px;
            border: none;
        """)

        self._update_transport_icons()

    def _update_transport_icons(self):
        """Rebuild transport button icons using the current theme color."""
        c = _color_to_hex(Colors.TEXT_PRIMARY)
        self._prev_btn.setIcon(_svg_icon(_SVG_PREV, c))
        self._play_btn.setIcon(
            _svg_icon(_SVG_PAUSE, c) if self._is_playing
            else _svg_icon(_SVG_PLAY, c))
        self._next_btn.setIcon(_svg_icon(_SVG_NEXT, c))

    # ── Signal Handlers ───────────────────────────────────────

    def _on_track_changed(self, track: dict):
        self._current_track = track
        self._title_label.setText(track.get("Title", "Unknown"))
        self._artist_label.setText(track.get("Artist", ""))
        self._album_label.setText(track.get("Album", ""))
        self._load_artwork(track)
        self.show()

    def _on_state_changed(self, state: str):
        self._is_playing = (state == "playing")
        self._update_transport_icons()

    def _on_position_changed(self, ms: int):
        if not self._seeking:
            self._seek_slider.setValue(ms)
        self._pos_label.setText(format_duration_mmss(ms) if ms > 0 else "0:00")

    def _on_duration_changed(self, ms: int):
        self._seek_slider.setRange(0, ms)
        self._dur_label.setText(format_duration_mmss(ms) if ms > 0 else "0:00")

    def _on_seek_pressed(self):
        self._seeking = True

    def _on_seek_released(self):
        self._seeking = False
        self._player.seek(self._seek_slider.value())

    # ── Artwork ───────────────────────────────────────────────

    def _load_artwork(self, track: dict):
        """Load artwork for the current track."""
        pixmap = None

        # Try PC art cache
        art_hash = track.get("_pc_art_hash")
        if art_hash:
            from ..pc_library_cache import get_pc_artwork
            pixmap = get_pc_artwork(art_hash)

        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(
                _ART_SIZE, _ART_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._art_label.setPixmap(scaled)
            self._art_label.setStyleSheet(f"""
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                border: none; background: transparent;
            """)
        else:
            self._art_label.clear()
            self._art_label.setText("\u266A")
            self._art_label.setFont(QFont(FONT_FAMILY, 20))
            self._art_label.setStyleSheet(f"""
                background: {Colors.SURFACE_HOVER};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                border: none;
                color: {Colors.TEXT_TERTIARY};
            """)
