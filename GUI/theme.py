"""
ThemeManager – central authority for theme mode, accent color, and palette.

Widgets that use inline stylesheets with accent or theme-sensitive colors
should connect to ``ThemeManager.instance().theme_changed`` and rebuild
their stylesheets in the handler.

Typical usage::

    from GUI.theme import ThemeManager
    tm = ThemeManager.instance()
    tm.theme_changed.connect(self._rebuild_style)
"""

import colorsys
from PyQt6.QtCore import QObject, pyqtSignal, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication


# ── Accent palette ──────────────────────────────────────────────────────────

ACCENT_PRESETS: dict[str, str] = {
    "blue":   "#409cff",
    "red":    "#e57373",
    "green":  "#81c784",
    "orange": "#ffb74d",
    "purple": "#ba68c8",
    "cyan":   "#4dd0e1",
    "pink":   "#f06292",
}


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


class AccentPalette:
    """Computed accent derivatives from a single hex base."""

    __slots__ = (
        "ACCENT", "ACCENT_LIGHT", "ACCENT_DARK",
        "ACCENT_DIM", "ACCENT_HOVER", "ACCENT_PRESS", "ACCENT_BORDER",
        "SELECTION", "BORDER_FOCUS",
        "rgb", "dark_rgb",
    )

    def __init__(self, hex_color: str):
        r, g, b = _hex_to_rgb(hex_color)
        self.rgb = (r, g, b)
        self.ACCENT = hex_color

        # Lighter tint for hover highlights
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        lr, lg, lb = colorsys.hsv_to_rgb(h, max(0, s - 0.10), min(1, v + 0.10))
        self.ACCENT_LIGHT = "#{:02x}{:02x}{:02x}".format(
            int(lr * 255), int(lg * 255), int(lb * 255))

        # Darker shade for gradient stops
        dr, dg, db = colorsys.hsv_to_rgb(h, min(1, s + 0.08), max(0, v - 0.20))
        dr, dg, db = int(dr * 255), int(dg * 255), int(db * 255)
        self.dark_rgb = (dr, dg, db)
        self.ACCENT_DARK = "#{:02x}{:02x}{:02x}".format(dr, dg, db)

        self.ACCENT_DIM = f"rgba({r},{g},{b},80)"
        self.ACCENT_HOVER = f"rgba({r},{g},{b},120)"
        self.ACCENT_PRESS = f"rgba({r},{g},{b},60)"
        self.ACCENT_BORDER = f"rgba({r},{g},{b},100)"
        self.SELECTION = f"rgba({r},{g},{b},90)"
        self.BORDER_FOCUS = f"rgba({r},{g},{b},150)"

    def rgba(self, alpha: int) -> str:
        """Return ``rgba(r,g,b,alpha)`` for the base accent color."""
        r, g, b = self.rgb
        return f"rgba({r},{g},{b},{alpha})"

    def dark_rgba(self, alpha: int) -> str:
        """Return ``rgba(r,g,b,alpha)`` for the darker accent shade."""
        r, g, b = self.dark_rgb
        return f"rgba({r},{g},{b},{alpha})"


# ── Color palettes ──────────────────────────────────────────────────────────

class _DarkPalette:
    """Colors for dark theme — neutral grays, no blue tint."""
    BG_DARK = "#1a1a1a"
    BG_MID = "#1e1e1e"
    SURFACE = "rgba(255,255,255,8)"
    SURFACE_ALT = "rgba(255,255,255,12)"
    SURFACE_RAISED = "rgba(255,255,255,18)"
    SURFACE_HOVER = "rgba(255,255,255,25)"
    SURFACE_ACTIVE = "rgba(255,255,255,35)"
    MENU_BG = "#2a2a2a"
    TEXT_PRIMARY = "rgba(255,255,255,230)"
    TEXT_SECONDARY = "rgba(255,255,255,150)"
    TEXT_TERTIARY = "rgba(255,255,255,100)"
    TEXT_DISABLED = "rgba(255,255,255,60)"
    BORDER = "rgba(255,255,255,30)"
    BORDER_SUBTLE = "rgba(255,255,255,15)"
    GRIDLINE = "rgba(255,255,255,12)"
    STAR = "#ffc857"
    DANGER = "#ff6b6b"
    SUCCESS = "#51cf66"
    WARNING = "#fcc419"
    DIALOG_BG = "#222222"
    TOOLTIP_BG = "#2a2a2a"
    # Scrollbar thumb
    SCROLL_THUMB = "rgba(255,255,255,30)"
    SCROLL_THUMB_HOVER = "rgba(255,255,255,50)"
    SCROLL_THUMB_PRESS = "rgba(255,255,255,65)"
    # QProxyStyle scrollbar QColors
    SCROLL_QCOLOR = QColor(255, 255, 255, 70)
    SCROLL_QCOLOR_HOVER = QColor(255, 255, 255, 110)
    SCROLL_QCOLOR_PRESS = QColor(255, 255, 255, 140)
    # QPalette base colors
    PAL_WINDOW = QColor(26, 26, 26)
    PAL_BASE = QColor(22, 22, 22)
    PAL_ALT_BASE = QColor(30, 30, 30)
    PAL_BUTTON = QColor(30, 30, 30)
    PAL_MID = QColor(30, 30, 30)
    PAL_DARK = QColor(18, 18, 18)
    PAL_MIDLIGHT = QColor(40, 40, 40)
    PAL_LIGHT = QColor(50, 50, 50)
    TEXT_QCOLOR = QColor(255, 255, 255)


class _LightPalette:
    """Colors for light theme — neutral grays, no blue tint."""
    BG_DARK = "#f0f0f0"
    BG_MID = "#f8f8f8"
    SURFACE = "rgba(0,0,0,4)"
    SURFACE_ALT = "rgba(0,0,0,6)"
    SURFACE_RAISED = "rgba(0,0,0,8)"
    SURFACE_HOVER = "rgba(0,0,0,12)"
    SURFACE_ACTIVE = "rgba(0,0,0,18)"
    MENU_BG = "#ffffff"
    TEXT_PRIMARY = "rgba(0,0,0,210)"
    TEXT_SECONDARY = "rgba(0,0,0,140)"
    TEXT_TERTIARY = "rgba(0,0,0,100)"
    TEXT_DISABLED = "rgba(0,0,0,50)"
    BORDER = "rgba(0,0,0,15)"
    BORDER_SUBTLE = "rgba(0,0,0,8)"
    GRIDLINE = "rgba(0,0,0,8)"
    STAR = "#e6a700"
    DANGER = "#d32f2f"
    SUCCESS = "#2e7d32"
    WARNING = "#ed6c02"
    DIALOG_BG = "#ffffff"
    TOOLTIP_BG = "#f5f5f5"
    # Scrollbar thumb
    SCROLL_THUMB = "rgba(0,0,0,20)"
    SCROLL_THUMB_HOVER = "rgba(0,0,0,35)"
    SCROLL_THUMB_PRESS = "rgba(0,0,0,50)"
    # QProxyStyle scrollbar QColors
    SCROLL_QCOLOR = QColor(0, 0, 0, 50)
    SCROLL_QCOLOR_HOVER = QColor(0, 0, 0, 90)
    SCROLL_QCOLOR_PRESS = QColor(0, 0, 0, 120)
    # QPalette base colors
    PAL_WINDOW = QColor(240, 240, 240)
    PAL_BASE = QColor(255, 255, 255)
    PAL_ALT_BASE = QColor(245, 245, 245)
    PAL_BUTTON = QColor(240, 240, 240)
    PAL_MID = QColor(210, 210, 210)
    PAL_DARK = QColor(180, 180, 180)
    PAL_MIDLIGHT = QColor(230, 230, 230)
    PAL_LIGHT = QColor(255, 255, 255)
    TEXT_QCOLOR = QColor(0, 0, 0)


# ── ThemeManager singleton ──────────────────────────────────────────────────

class ThemeManager(QObject):
    """Singleton managing theme mode and accent color.

    Signals:
        theme_changed  – emitted when the palette or accent changes.
                         Widgets should reconnect their stylesheets.
    """

    theme_changed = pyqtSignal()

    _instance: "ThemeManager | None" = None

    @classmethod
    def instance(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = ThemeManager()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._mode: str = "dark"  # "dark", "light", "system"
        self._accent_name: str = "blue"
        self._accent = AccentPalette(ACCENT_PRESETS["blue"])
        self._palette = _DarkPalette
        self._system_listening = False

    # ── Public API ──────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def accent_name(self) -> str:
        return self._accent_name

    @property
    def accent(self) -> AccentPalette:
        return self._accent

    @property
    def palette(self):
        return self._palette

    @property
    def is_dark(self) -> bool:
        if self._mode == "system":
            return self._system_is_dark()
        return self._mode == "dark"

    def set_mode(self, mode: str) -> None:
        """Set theme mode ('dark', 'light', or 'system')."""
        if mode not in ("dark", "light", "system"):
            return
        if mode == self._mode:
            return
        self._mode = mode
        if mode == "system":
            self._start_system_listener()
        self._update_palette()
        self._apply()
        self.theme_changed.emit()

    def set_accent(self, name: str) -> None:
        """Set accent color by preset name."""
        if name not in ACCENT_PRESETS or name == self._accent_name:
            return
        self._accent_name = name
        self._accent = AccentPalette(ACCENT_PRESETS[name])
        self._apply()
        self.theme_changed.emit()

    def apply_initial(self) -> None:
        """Apply theme to the running QApplication. Call once after init."""
        self._update_palette()
        self._apply()

    # ── Internal ────────────────────────────────────────────────

    def _update_palette(self) -> None:
        self._palette = _DarkPalette if self.is_dark else _LightPalette

    def _apply(self) -> None:
        """Rebuild and apply the global stylesheet + QPalette."""
        app = QApplication.instance()
        if app is None:
            return

        from GUI.styles import build_app_stylesheet, DarkScrollbarStyle
        app.setStyleSheet(build_app_stylesheet())

        # Update the proxy style scrollbar colors
        style = app.style()
        if isinstance(style, DarkScrollbarStyle):
            p = self._palette
            style._THUMB = p.SCROLL_QCOLOR
            style._THUMB_HOVER = p.SCROLL_QCOLOR_HOVER
            style._THUMB_PRESS = p.SCROLL_QCOLOR_PRESS

        # Update QPalette
        from PyQt6.QtGui import QPalette
        p = self._palette
        a = self._accent
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window, p.PAL_WINDOW)
        pal.setColor(QPalette.ColorRole.WindowText, p.TEXT_QCOLOR)
        pal.setColor(QPalette.ColorRole.Base, p.PAL_BASE)
        pal.setColor(QPalette.ColorRole.AlternateBase, p.PAL_ALT_BASE)
        pal.setColor(QPalette.ColorRole.Text, p.TEXT_QCOLOR)
        pal.setColor(QPalette.ColorRole.Button, p.PAL_BUTTON)
        pal.setColor(QPalette.ColorRole.ButtonText, p.TEXT_QCOLOR)
        pal.setColor(QPalette.ColorRole.Highlight, QColor(a.ACCENT))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        pal.setColor(QPalette.ColorRole.Mid, p.PAL_MID)
        pal.setColor(QPalette.ColorRole.Dark, p.PAL_DARK)
        pal.setColor(QPalette.ColorRole.Midlight, p.PAL_MIDLIGHT)
        pal.setColor(QPalette.ColorRole.Shadow, QColor(0, 0, 0))
        pal.setColor(QPalette.ColorRole.Light, p.PAL_LIGHT)
        app.setPalette(pal)

    def _system_is_dark(self) -> bool:
        app = QApplication.instance()
        if app is None:
            return True
        try:
            scheme = app.styleHints().colorScheme()
            return scheme == Qt.ColorScheme.Dark
        except AttributeError:
            return True  # Fallback for older Qt6

    def _start_system_listener(self) -> None:
        if self._system_listening:
            return
        app = QApplication.instance()
        if app is None:
            return
        try:
            app.styleHints().colorSchemeChanged.connect(self._on_system_changed)
            self._system_listening = True
        except AttributeError:
            pass  # Older Qt6 without colorSchemeChanged

    def _on_system_changed(self) -> None:
        if self._mode != "system":
            return
        self._update_palette()
        self._apply()
        self.theme_changed.emit()
