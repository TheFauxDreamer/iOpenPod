from PyQt6.QtCore import Qt, QPropertyAnimation, QAbstractAnimation, QEasingCurve, QSequentialAnimationGroup, QPauseAnimation
from PyQt6.QtCore import pyqtProperty  # type: ignore[attr-defined]
from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QPainter, QFontMetrics, QEnterEvent

# Gap (in pixels) between the end of text and the wrapped copy
_MARQUEE_GAP = 40


class ScrollingLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._offset = 0
        self.animation_group = None
        self._auto_scroll = False
        self._marquee = False  # True when using wrap-around marquee style
        self.setToolTip(text)

    def getOffset(self):
        return self._offset

    def setOffset(self, value):
        self._offset = value
        self.update()

    offset = pyqtProperty(int, fget=getOffset, fset=setOffset)

    def paintEvent(self, a0):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setClipRect(self.rect())
        fm = QFontMetrics(self.font())
        full_width = fm.horizontalAdvance(self.text())
        flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if full_width <= self.width():
            # Text fits — draw normally
            painter.drawText(self.rect(), flags, self.text())
            return

        if self._marquee:
            # Continuous marquee: draw text twice with a gap for smooth wrapping
            cycle = full_width + _MARQUEE_GAP
            x = -self._offset
            # First copy
            r1 = self.rect()
            r1.setWidth(full_width)
            r1.moveLeft(x)
            painter.drawText(r1, flags, self.text())
            # Second copy (wraps around)
            r2 = self.rect()
            r2.setWidth(full_width)
            r2.moveLeft(x + cycle)
            painter.drawText(r2, flags, self.text())
        else:
            # Simple offset (hover mode): slide text left
            draw_rect = self.rect()
            draw_rect.setWidth(full_width)
            draw_rect.translate(-self._offset, 0)
            painter.drawText(draw_rect, flags, self.text())

    def setAutoScroll(self, enabled: bool):
        """Enable auto-scrolling when text overflows (no hover needed)."""
        self._auto_scroll = enabled
        if enabled:
            self._start_scroll_if_needed()
        else:
            self._marquee = False
            self._stop_scroll()

    def setText(self, text: str):
        super().setText(text)
        self.setToolTip(text)
        if self._auto_scroll:
            # Delay slightly so layout has settled and width is correct
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, self._start_scroll_if_needed)

    def _start_scroll_if_needed(self):
        """Start scrolling animation if text overflows."""
        fm = QFontMetrics(self.font())
        full_width = fm.horizontalAdvance(self.text())
        if full_width > self.width() > 0:
            if self._auto_scroll:
                self._start_marquee_animation(full_width)
            else:
                self._start_scroll_animation(full_width - self.width())
        else:
            self._marquee = False
            self._stop_scroll()

    def _stop_scroll(self):
        if self.animation_group is not None:
            self.animation_group.stop()
            self.animation_group.deleteLater()
            self.animation_group = None
            self.setOffset(0)

    def _start_marquee_animation(self, full_width: int):
        """Continuous marquee: text scrolls left and wraps around smoothly."""
        self._marquee = True
        cycle = full_width + _MARQUEE_GAP
        scroll_speed = 0.03  # pixels per millisecond
        duration = int(cycle / scroll_speed)
        pause_duration = 2000  # ms pause at start before each cycle

        if self.animation_group is not None and self.animation_group.state() == QAbstractAnimation.State.Running:
            self.animation_group.stop()
        if self.animation_group is not None:
            self.animation_group.deleteLater()

        self.animation_group = QSequentialAnimationGroup(self)

        # Pause at start
        self.animation_group.addAnimation(QPauseAnimation(pause_duration))

        # Scroll through one full cycle (text + gap)
        scroll_anim = QPropertyAnimation(self, b"offset")
        scroll_anim.setDuration(duration)
        scroll_anim.setStartValue(0)
        scroll_anim.setEndValue(cycle)
        scroll_anim.setEasingCurve(QEasingCurve.Type.Linear)
        self.animation_group.addAnimation(scroll_anim)

        self.animation_group.setLoopCount(-1)
        self.animation_group.start()

    def _start_scroll_animation(self, scroll_distance: int):
        """Hover-triggered scroll: slides text to reveal the end, then back."""
        self._marquee = False
        scroll_speed = 0.025  # pixels per millisecond
        duration = int(scroll_distance / scroll_speed)
        pause_duration = 1200  # ms to pause at each end

        if self.animation_group is not None and self.animation_group.state() == QAbstractAnimation.State.Running:
            self.animation_group.stop()
        if self.animation_group is not None:
            self.animation_group.deleteLater()

        self.animation_group = QSequentialAnimationGroup(self)

        self.animation_group.addAnimation(QPauseAnimation(pause_duration))

        forward_anim = QPropertyAnimation(self, b"offset")
        forward_anim.setDuration(duration)
        forward_anim.setStartValue(0)
        forward_anim.setEndValue(scroll_distance)
        forward_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.animation_group.addAnimation(forward_anim)

        self.animation_group.addAnimation(QPauseAnimation(pause_duration))

        backward_anim = QPropertyAnimation(self, b"offset")
        backward_anim.setDuration(duration)
        backward_anim.setStartValue(scroll_distance)
        backward_anim.setEndValue(0)
        backward_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.animation_group.addAnimation(backward_anim)

        self.animation_group.addAnimation(QPauseAnimation(pause_duration))

        self.animation_group.setLoopCount(-1)
        self.animation_group.start()

    def enterEvent(self, event: QEnterEvent | None):
        if not self._auto_scroll:
            fm = QFontMetrics(self.font())
            full_width = fm.horizontalAdvance(self.text())
            if full_width > self.width():
                self._start_scroll_animation(full_width - self.width())
        super().enterEvent(event)

    def leaveEvent(self, a0):
        if not self._auto_scroll:
            self._marquee = False
            self._stop_scroll()
        super().leaveEvent(a0)
