"""
CategoryTabBar – horizontal tab bar for switching between content categories.

Styled as flat text tabs with an accent-colored underline on the active tab,
similar to iTunes / Apple Music.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QSizePolicy

from ..styles import Colors, FONT_FAMILY


CATEGORIES = ["Albums", "Artists", "Songs", "Genres", "Playlists"]


class CategoryTabBar(QFrame):
    """Horizontal tab bar emitting *category_changed* when the user clicks a tab."""

    category_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self._buttons: dict[str, QPushButton] = {}
        self._active: str = CATEGORIES[0]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(4)

        for cat in CATEGORIES:
            btn = QPushButton(cat)
            btn.setFont(QFont(FONT_FAMILY, 11, QFont.Weight.DemiBold))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setCheckable(True)
            btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
            btn.clicked.connect(lambda checked, c=cat: self._on_tab_clicked(c))
            self._buttons[cat] = btn
            layout.addWidget(btn)

        layout.addStretch()

        # Apply styles and set initial active tab
        self._rebuild_styles()
        self._buttons[self._active].setChecked(True)

        from ..theme import ThemeManager
        ThemeManager.instance().theme_changed.connect(self._rebuild_styles)

    def setActiveCategory(self, category: str):
        """Programmatically set the active tab without emitting a signal."""
        if category not in self._buttons:
            return
        self._active = category
        for cat, btn in self._buttons.items():
            btn.setChecked(cat == category)

    def _on_tab_clicked(self, category: str):
        if category == self._active:
            return
        self._active = category
        for cat, btn in self._buttons.items():
            btn.setChecked(cat == category)
        self.category_changed.emit(category)

    def _rebuild_styles(self):
        from ..theme import ThemeManager
        a = ThemeManager.instance().accent
        r, g, b = a.rgb

        self.setStyleSheet(f"""
            CategoryTabBar {{
                background: transparent;
                border: none;
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
            }}
            QPushButton {{
                background: transparent;
                border: none;
                border-bottom: 2px solid transparent;
                color: {Colors.TEXT_SECONDARY};
                padding: 6px 12px 4px 12px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                color: {Colors.TEXT_PRIMARY};
            }}
            QPushButton:checked {{
                color: {Colors.TEXT_PRIMARY};
                border-bottom: 2px solid rgba({r},{g},{b},200);
            }}
        """)
