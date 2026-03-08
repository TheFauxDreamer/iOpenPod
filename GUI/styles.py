"""
Centralized style definitions for iOpenPod.

All colors, dimensions, and reusable stylesheet fragments live here so that
every widget draws from a single visual language.

The ``Colors`` object is a dynamic proxy – its attributes change when the
theme or accent color is updated via ``ThemeManager``.  Widgets that embed
color values into inline stylesheets must reconnect on
``ThemeManager.theme_changed`` to pick up changes.
"""

import sys

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QProxyStyle,
    QStyle,
    QStyleOptionComplex,
    QStyleOptionSlider,
)

# ── Cross-platform font ─────────────────────────────────────────────────────

if sys.platform == "darwin":
    FONT_FAMILY = ".AppleSystemUIFont"
    MONO_FONT_FAMILY = "Menlo"
    _CSS_FONT_STACK = '".AppleSystemUIFont", "Helvetica Neue"'
elif sys.platform == "win32":
    FONT_FAMILY = "Segoe UI"
    MONO_FONT_FAMILY = "Consolas"
    _CSS_FONT_STACK = '"Segoe UI"'
else:
    FONT_FAMILY = "Noto Sans"
    MONO_FONT_FAMILY = "Noto Sans Mono"
    _CSS_FONT_STACK = (
        '"Noto Sans", "Noto Sans Symbols 2", "Noto Emoji",'
        ' "Ubuntu", "DejaVu Sans"'
    )

# ── Color proxy ─────────────────────────────────────────────────────────────


class _ColorsProxy:
    """Dynamic proxy that delegates to ThemeManager's active palette + accent.

    Import and use as before::

        from GUI.styles import Colors
        Colors.ACCENT      # current accent hex
        Colors.BG_DARK     # current theme background
    """

    # Accent attributes are served from AccentPalette
    _ACCENT_ATTRS = frozenset({
        "ACCENT", "ACCENT_LIGHT", "ACCENT_DIM", "ACCENT_HOVER",
        "ACCENT_PRESS", "ACCENT_BORDER", "SELECTION", "BORDER_FOCUS",
    })

    def __getattr__(self, name: str):
        # Lazy import to avoid circular import at module load time
        from GUI.theme import ThemeManager
        tm = ThemeManager.instance()
        if name in self._ACCENT_ATTRS:
            return getattr(tm.accent, name)
        return getattr(tm.palette, name)


Colors = _ColorsProxy()


# ── Metrics ──────────────────────────────────────────────────────────────────

class Metrics:
    """Shared dimension constants."""
    BORDER_RADIUS = 8
    BORDER_RADIUS_SM = 6
    BORDER_RADIUS_LG = 10
    BORDER_RADIUS_XL = 12

    GRID_ITEM_W = 172
    GRID_ITEM_H = 224
    GRID_ART_SIZE = 152
    GRID_SPACING = 14

    SIDEBAR_WIDTH = 220
    SCROLLBAR_W = 8
    SCROLLBAR_MIN_H = 40

    BTN_PADDING_V = 7
    BTN_PADDING_H = 14


# ── Custom proxy style for scrollbar painting ───────────────────────────────

class DarkScrollbarStyle(QProxyStyle):
    """Overrides Fusion scrollbar painting with thin, dark, rounded bars.

    Qt stylesheet-based scrollbar styling is unreliable on Windows with
    Fusion (CSS is silently ignored). This proxy style paints scrollbars
    directly via QPainter so they always render correctly.

    Thumb colors are mutable so ThemeManager can update them at runtime.
    """

    _THICKNESS = 8                         # thin like macOS/VS Code
    _MIN_HANDLE = 36                       # minimum thumb length
    _TRACK = QColor(0, 0, 0, 0)           # invisible track
    _THUMB = QColor(255, 255, 255, 70)
    _THUMB_HOVER = QColor(255, 255, 255, 110)
    _THUMB_PRESS = QColor(255, 255, 255, 140)

    def __init__(self, base_key: str = "Fusion"):
        super().__init__(base_key)

    # -- Metrics: make scrollbars thin --

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (
            QStyle.PixelMetric.PM_ScrollBarExtent,
        ):
            return self._THICKNESS
        if metric == QStyle.PixelMetric.PM_ScrollBarSliderMin:
            return self._MIN_HANDLE
        return super().pixelMetric(metric, option, widget)

    # -- Sub-control rectangles --

    def subControlRect(self, cc, opt, sc, widget=None):
        if cc != QStyle.ComplexControl.CC_ScrollBar or not isinstance(opt, QStyleOptionSlider):
            return super().subControlRect(cc, opt, sc, widget)

        r = opt.rect
        horiz = opt.orientation == Qt.Orientation.Horizontal
        length = r.width() if horiz else r.height()

        # No step buttons
        if sc in (
            QStyle.SubControl.SC_ScrollBarAddLine,
            QStyle.SubControl.SC_ScrollBarSubLine,
        ):
            return QRect()

        # Groove = full rect
        if sc == QStyle.SubControl.SC_ScrollBarGroove:
            return r

        # Slider handle
        if sc == QStyle.SubControl.SC_ScrollBarSlider:
            rng = opt.maximum - opt.minimum
            if rng <= 0:
                return r  # full when no range
            page = max(opt.pageStep, 1)
            handle_len = max(
                int(length * page / (rng + page)),
                self._MIN_HANDLE,
            )
            available = length - handle_len
            if available <= 0:
                pos = 0
            else:
                pos = int(available * (opt.sliderValue - opt.minimum) / rng)
            if horiz:
                return QRect(r.x() + pos, r.y(), handle_len, r.height())
            else:
                return QRect(r.x(), r.y() + pos, r.width(), handle_len)

        # Page areas
        if sc in (
            QStyle.SubControl.SC_ScrollBarAddPage,
            QStyle.SubControl.SC_ScrollBarSubPage,
        ):
            slider = self.subControlRect(cc, opt, QStyle.SubControl.SC_ScrollBarSlider, widget)
            if sc == QStyle.SubControl.SC_ScrollBarSubPage:
                if horiz:
                    return QRect(r.x(), r.y(), slider.x() - r.x(), r.height())
                else:
                    return QRect(r.x(), r.y(), r.width(), slider.y() - r.y())
            else:
                if horiz:
                    end = slider.x() + slider.width()
                    return QRect(end, r.y(), r.right() - end + 1, r.height())
                else:
                    end = slider.y() + slider.height()
                    return QRect(r.x(), end, r.width(), r.bottom() - end + 1)

        return super().subControlRect(cc, opt, sc, widget)

    # -- Hit testing --

    def hitTestComplexControl(self, control, option, pos, widget=None):
        if control == QStyle.ComplexControl.CC_ScrollBar and isinstance(option, QStyleOptionSlider):
            slider = self.subControlRect(control, option, QStyle.SubControl.SC_ScrollBarSlider, widget)
            if slider.contains(pos):
                return QStyle.SubControl.SC_ScrollBarSlider
            groove = self.subControlRect(control, option, QStyle.SubControl.SC_ScrollBarGroove, widget)
            if groove.contains(pos):
                horiz = option.orientation == Qt.Orientation.Horizontal
                if (horiz and pos.x() < slider.x()) or (not horiz and pos.y() < slider.y()):
                    return QStyle.SubControl.SC_ScrollBarSubPage
                return QStyle.SubControl.SC_ScrollBarAddPage
            return QStyle.SubControl.SC_None
        return super().hitTestComplexControl(control, option, pos, widget)

    # -- Draw the scrollbar --

    def drawComplexControl(self, control, option, painter, widget=None):
        if control != QStyle.ComplexControl.CC_ScrollBar or not isinstance(option, QStyleOptionSlider):
            super().drawComplexControl(control, option, painter, widget)
            return

        # Guard against None painter (can happen during widget destruction)
        if painter is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # No track — completely transparent

        # Handle (pill shape)
        slider = self.subControlRect(control, option, QStyle.SubControl.SC_ScrollBarSlider, widget)
        if slider.isValid() and not slider.isEmpty():
            pressed = bool(option.state & QStyle.StateFlag.State_Sunken)
            active_sc = option.activeSubControls if isinstance(option, QStyleOptionComplex) else QStyle.SubControl.SC_None
            hovered = bool(
                (option.state & QStyle.StateFlag.State_MouseOver)
                and (active_sc & QStyle.SubControl.SC_ScrollBarSlider)  # noqa: W503
            )

            if pressed:
                color = self._THUMB_PRESS
            elif hovered:
                color = self._THUMB_HOVER
            else:
                color = self._THUMB

            horiz = option.orientation == Qt.Orientation.Horizontal
            # Inset to create a floating pill centered in the track
            pad = 2  # padding from edge of scrollbar track
            if horiz:
                thumb_h = max(slider.height() - pad * 2, 4)
                adj = QRect(
                    slider.x() + 2, slider.y() + pad,
                    slider.width() - 4, thumb_h,
                )
            else:
                thumb_w = max(slider.width() - pad * 2, 4)
                adj = QRect(
                    slider.x() + pad, slider.y() + 2,
                    thumb_w, slider.height() - 4,
                )

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            # Fully rounded — radius = half the shorter dimension
            r = min(adj.width(), adj.height()) / 2.0
            painter.drawRoundedRect(adj, r, r)

        painter.restore()

    # -- Suppress default Fusion scrollbar primitives --

    def drawPrimitive(self, element, option, painter, widget=None):
        # Skip the default scrollbar arrow drawing
        if element in (
            QStyle.PrimitiveElement.PE_PanelScrollAreaCorner,
        ):
            return  # paint nothing — transparent corner
        super().drawPrimitive(element, option, painter, widget)


# ── Reusable stylesheet fragments ───────────────────────────────────────────

def scrollbar_css(width: int = Metrics.SCROLLBAR_W, orient: str = "vertical") -> str:
    """Minimal modern scrollbar — thin track, rounded thumb.

    Covers every pseudo-element so that native platform chrome never leaks
    through (especially on Windows where the default blue bar is visible
    if any sub-element is left unstyled).
    """
    from GUI.theme import ThemeManager
    p = ThemeManager.instance().palette

    bar = f"QScrollBar:{orient}"
    r = max(width // 2, 1)
    if orient == "vertical":
        return f"""
            {bar} {{
                background: transparent;
                width: {width}px;
                margin: 0;
                padding: 2px 1px;
                border: none;
            }}
            {bar}::handle {{
                background: {p.SCROLL_THUMB};
                border-radius: {r}px;
                min-height: {Metrics.SCROLLBAR_MIN_H}px;
            }}
            {bar}::handle:hover {{
                background: {p.SCROLL_THUMB_HOVER};
            }}
            {bar}::handle:pressed {{
                background: {p.SCROLL_THUMB_PRESS};
            }}
            {bar}::add-line, {bar}::sub-line {{
                border: none; background: none; height: 0px; width: 0px;
            }}
            {bar}::add-page, {bar}::sub-page {{
                background: none;
            }}
            {bar}::up-arrow, {bar}::down-arrow {{
                background: none; width: 0px; height: 0px;
            }}
        """
    else:
        return f"""
            {bar} {{
                background: transparent;
                height: {width}px;
                margin: 0;
                padding: 1px 2px;
                border: none;
            }}
            {bar}::handle {{
                background: {p.SCROLL_THUMB};
                border-radius: {r}px;
                min-width: {Metrics.SCROLLBAR_MIN_H}px;
            }}
            {bar}::handle:hover {{
                background: {p.SCROLL_THUMB_HOVER};
            }}
            {bar}::handle:pressed {{
                background: {p.SCROLL_THUMB_PRESS};
            }}
            {bar}::add-line, {bar}::sub-line {{
                border: none; background: none; height: 0px; width: 0px;
            }}
            {bar}::add-page, {bar}::sub-page {{
                background: none;
            }}
            {bar}::left-arrow, {bar}::right-arrow {{
                background: none; width: 0px; height: 0px;
            }}
        """


def scrollbar_corner_css() -> str:
    """Style the corner widget where horizontal & vertical scrollbars meet."""
    return """
        QAbstractScrollArea::corner {
            background: transparent;
            border: none;
        }
    """


def btn_css(
    bg: str = "",
    bg_hover: str = "",
    bg_press: str = "",
    fg: str = "",
    border: str = "none",
    radius: int = Metrics.BORDER_RADIUS_SM,
    padding: str = f"{Metrics.BTN_PADDING_V}px {Metrics.BTN_PADDING_H}px",
    extra: str = "",
) -> str:
    """Standard button stylesheet."""
    _bg = bg or Colors.SURFACE_RAISED
    _bg_hover = bg_hover or Colors.SURFACE_HOVER
    _bg_press = bg_press or Colors.SURFACE_ALT
    _fg = fg or Colors.TEXT_PRIMARY
    return f"""
        QPushButton {{
            background: {_bg};
            border: {border};
            border-radius: {radius}px;
            color: {_fg};
            padding: {padding};
            {extra}
        }}
        QPushButton:hover {{
            background: {_bg_hover};
        }}
        QPushButton:pressed {{
            background: {_bg_press};
        }}
    """


def accent_btn_css() -> str:
    """Primary action button (accent colored)."""
    return btn_css(
        bg=Colors.ACCENT_DIM,
        bg_hover=Colors.ACCENT_HOVER,
        bg_press=Colors.ACCENT_PRESS,
        border=f"1px solid {Colors.ACCENT_BORDER}",
    )


# ── Application-level stylesheet ────────────────────────────────────────────

def build_app_stylesheet() -> str:
    """Build the global QApplication stylesheet from the active theme."""
    from GUI.theme import ThemeManager
    tm = ThemeManager.instance()
    p = tm.palette
    a = tm.accent

    return f"""
    /* ── Base ──────────────────────────────────────────────────── */
    QMainWindow {{
        background: {p.BG_DARK};
    }}
    QWidget {{
        font-family: {_CSS_FONT_STACK};
        color: {p.TEXT_PRIMARY};
    }}
    QStackedWidget {{
        background: transparent;
    }}
    QFrame {{
        background: transparent;
        border: none;
    }}
    QLabel {{
        color: {p.TEXT_PRIMARY};
    }}

    /* ── Tooltips ──────────────────────────────────────────────── */
    QToolTip {{
        background: {p.TOOLTIP_BG};
        color: {p.TEXT_PRIMARY};
        border: 1px solid {p.BORDER};
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 11px;
    }}

    /* ── Splitter handle ───────────────────────────────────────── */
    QSplitter::handle {{
        background: {p.BORDER_SUBTLE};
    }}
    QSplitter::handle:hover {{
        background: {a.ACCENT};
    }}
    QSplitter::handle:pressed {{
        background: {a.ACCENT_LIGHT};
    }}

    /* ── Message boxes ─────────────────────────────────────────── */
    QMessageBox {{
        background: {p.DIALOG_BG};
        color: {p.TEXT_PRIMARY};
    }}
    QMessageBox QLabel {{
        color: {p.TEXT_PRIMARY};
    }}
    QMessageBox QPushButton {{
        background: {p.SURFACE_RAISED};
        border: 1px solid {p.BORDER};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        color: {p.TEXT_PRIMARY};
        padding: 6px 20px;
        min-width: 70px;
    }}
    QMessageBox QPushButton:hover {{
        background: {p.SURFACE_HOVER};
    }}

    /* ── Dialog ─────────────────────────────────────────────────── */
    QDialog {{
        background: {p.DIALOG_BG};
        color: {p.TEXT_PRIMARY};
    }}

    /* ── Focus ring ─────────────────────────────────────────────── */
    QPushButton:focus {{
        outline: none;
        border: 1px solid {a.BORDER_FOCUS};
    }}
"""


# Backwards compatibility: keep APP_STYLESHEET as a lazy property for any
# import-time references, but it should not be used directly anymore.
# New code should call build_app_stylesheet() or let ThemeManager handle it.
APP_STYLESHEET = ""  # Placeholder — ThemeManager.apply_initial() sets the real one
