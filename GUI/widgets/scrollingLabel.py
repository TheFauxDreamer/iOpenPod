from PyQt6.QtCore import Qt, QPropertyAnimation, QAbstractAnimation, QEasingCurve, QSequentialAnimationGroup, QPauseAnimation
from PyQt6.QtCore import pyqtProperty  # type: ignore[attr-defined]
from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QPainter, QFontMetrics, QEnterEvent


class ScrollingLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._offset = 0
        self.animation_group = None
        self._auto_scroll = False
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
        fm = QFontMetrics(self.font())
        full_width = fm.horizontalAdvance(self.text())
        if full_width > self.width():
            draw_rect = self.rect()
            draw_rect.setWidth(full_width)
            draw_rect.translate(-self._offset, 0)
            painter.drawText(
                draw_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.text())
        else:
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.text())

    def setAutoScroll(self, enabled: bool):
        """Enable auto-scrolling when text overflows (no hover needed)."""
        self._auto_scroll = enabled
        if enabled:
            self._start_scroll_if_needed()
        else:
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
            self._start_scroll_animation(full_width - self.width())

    def _stop_scroll(self):
        if self.animation_group is not None:
            self.animation_group.stop()
            self.animation_group.deleteLater()
            self.animation_group = None
            self.setOffset(0)

    def _start_scroll_animation(self, scroll_distance: int):
        """Create and start the scroll animation for the given distance."""
        scroll_speed = 0.025  # pixels per millisecond
        duration = int(scroll_distance / scroll_speed)
        pause_duration = 1200  # ms to pause at each end

        if self.animation_group is not None and self.animation_group.state() == QAbstractAnimation.State.Running:
            self.animation_group.stop()
        if self.animation_group is not None:
            self.animation_group.deleteLater()

        self.animation_group = QSequentialAnimationGroup(self)

        start_pause = QPauseAnimation(pause_duration)
        self.animation_group.addAnimation(start_pause)

        forward_anim = QPropertyAnimation(self, b"offset")
        forward_anim.setDuration(duration)
        forward_anim.setStartValue(0)
        forward_anim.setEndValue(scroll_distance)
        forward_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.animation_group.addAnimation(forward_anim)

        end_pause = QPauseAnimation(pause_duration)
        self.animation_group.addAnimation(end_pause)

        backward_anim = QPropertyAnimation(self, b"offset")
        backward_anim.setDuration(duration)
        backward_anim.setStartValue(scroll_distance)
        backward_anim.setEndValue(0)
        backward_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.animation_group.addAnimation(backward_anim)

        loop_pause = QPauseAnimation(pause_duration)
        self.animation_group.addAnimation(loop_pause)

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
            self._stop_scroll()
        super().leaveEvent(a0)
