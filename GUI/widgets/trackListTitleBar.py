from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QHBoxLayout, QFrame, QLabel, QPushButton, QWidget
from PyQt6.QtGui import QFont

from ..styles import Colors, FONT_FAMILY


def _title_bar_css(r: int, g: int, b: int) -> str:
    """Generate a subtle tinted title bar stylesheet for the given RGB color."""
    return f"""
        QFrame {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba({r},{g},{b},50), stop:1 rgba({r},{g},{b},30));
            border: none;
            border-bottom: 1px solid rgba({r},{g},{b},60);
            border-radius: 0px;
        }}
        QLabel {{
            font-weight: 600;
            font-size: 12px;
            color: {Colors.TEXT_PRIMARY};
            background: transparent;
        }}
        QPushButton {{
            background-color: transparent;
            border: none;
            color: {Colors.TEXT_SECONDARY};
            font-size: 14px;
            font-weight: bold;
            width: 26px;
            height: 26px;
            border-radius: 4px;
        }}
        QPushButton:hover {{
            background-color: rgba({r},{g},{b},40);
            color: {Colors.TEXT_PRIMARY};
        }}
        QPushButton:pressed {{
            background-color: rgba({r},{g},{b},60);
        }}
    """


def _default_css() -> str:
    """Build the default accent-colored title bar CSS."""
    from ..theme import ThemeManager
    a = ThemeManager.instance().accent
    r, g, b = a.rgb
    return _title_bar_css(r, g, b)


class TrackListTitleBar(QFrame):
    """Draggable title bar for the track list panel."""

    def __init__(self, splitterToControl):
        super().__init__()
        self.splitter = splitterToControl
        self.dragging = False
        self.dragStartPos = QPoint()
        self.setMouseTracking(True)
        self.titleBarLayout = QHBoxLayout(self)
        self.titleBarLayout.setContentsMargins(12, 0, 8, 0)
        self.splitter.splitterMoved.connect(self.enforceMinHeight)

        self.setMinimumHeight(34)
        self.setMaximumHeight(34)
        self.setFixedHeight(34)

        self._custom_color: tuple[int, int, int] | None = None
        self.setStyleSheet(_default_css())

        from ..theme import ThemeManager
        ThemeManager.instance().theme_changed.connect(self._rebuild_styles)

        self.title = QLabel("Tracks")
        self.title.setFont(QFont(FONT_FAMILY, 12, QFont.Weight.DemiBold))

        self.button1 = QPushButton("▼")
        self.button1.setToolTip("Minimize")
        self.button1.clicked.connect(self._toggleMinimize)

        self.button2 = QPushButton("▲")
        self.button2.setToolTip("Maximize")
        self.button2.clicked.connect(self._toggleMaximize)

        self.titleBarLayout.addWidget(self.title)
        self.titleBarLayout.addStretch()
        self.titleBarLayout.addWidget(self.button1)
        self.titleBarLayout.addWidget(self.button2)

    def setTitle(self, title: str):
        """Set the title text."""
        self.title.setText(title)

    def setColor(self, r: int, g: int, b: int):
        """Set the title bar tint to the given RGB color."""
        self._custom_color = (r, g, b)
        self.setStyleSheet(_title_bar_css(r, g, b))

    def resetColor(self):
        """Reset to the default accent gradient."""
        self._custom_color = None
        self.setStyleSheet(_default_css())

    def _rebuild_styles(self):
        """Rebuild stylesheet with current theme colors."""
        if self._custom_color:
            self.setStyleSheet(_title_bar_css(*self._custom_color))
        else:
            self.setStyleSheet(_default_css())

    def _toggleMinimize(self):
        """Minimize the track list panel."""
        sizes = self.splitter.sizes()
        total = sum(sizes)
        # Set track panel to minimum (just title bar)
        self.splitter.setSizes([total - 40, 40])

    def _toggleMaximize(self):
        """Maximize the track list panel."""
        sizes = self.splitter.sizes()
        total = sum(sizes)
        # Set track panel to 80% of space
        self.splitter.setSizes([int(total * 0.2), int(total * 0.8)])

    def mousePressEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            if self.childAt(a0.pos()) is None:
                self.dragging = True
                self.dragStartPos = a0.globalPosition().toPoint()
                a0.accept()
            else:
                a0.ignore()

    def mouseMoveEvent(self, a0):
        if self.dragging and a0:
            self.dragStartPos = a0.globalPosition().toPoint()

            new_pos = self.splitter.mapFromGlobal(
                a0.globalPosition().toPoint()).y()

            parent = self.splitter.parent()
            max_pos = parent.height() - self.splitter.handleWidth() if parent else 0

            new_pos = max(0, min(new_pos, max_pos))

            # move the splitter handle
            self.splitter.moveSplitter(new_pos, 1)
            a0.accept()
        elif a0:
            a0.ignore()

    def mouseReleaseEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            a0.accept()

    def enterEvent(self, event):  # type: ignore[override]
        if event:
            pos = event.position().toPoint()
            if self.childAt(pos) is None:
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            else:
                self.unsetCursor()

    def leaveEvent(self, a0):
        self.unsetCursor()
        super().leaveEvent(a0)

    def enforceMinHeight(self):
        sizes = self.splitter.sizes()
        min_height = self.minimumHeight()
        parent = self.parent()
        if sizes[1] <= min_height:
            if parent:
                for child in parent.children():
                    if isinstance(child, QWidget) and child != self:
                        child.hide()
        else:
            if parent:
                for child in parent.children():
                    if isinstance(child, QWidget):
                        child.show()

        if sizes[1] < min_height:
            total = sizes[0] + sizes[1]
            sizes[1] = min_height
            sizes[0] = max(total - min_height, 0)
            self.splitter.setSizes(sizes)
