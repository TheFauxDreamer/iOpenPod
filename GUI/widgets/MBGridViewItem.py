import json
import logging
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QMimeData, QPoint
from PyQt6.QtWidgets import QLabel, QFrame, QVBoxLayout, QApplication
from PyQt6.QtGui import QFont, QPixmap, QCursor, QImage, QDrag
from ..imgMaker import find_image_by_imgId, get_artworkdb_cached
from ..styles import Colors, FONT_FAMILY, Metrics
from .scrollingLabel import ScrollingLabel

log = logging.getLogger(__name__)


class MusicBrowserGridItem(QFrame):
    """A clickable grid item that displays album art, title, and subtitle."""
    clicked = pyqtSignal(dict)  # Emits item data when clicked

    def __init__(self, title: str, subtitle: str, mhiiLink, item_data: dict | None = None):
        super().__init__()
        self.title_text = title
        self.subtitle_text = subtitle
        self.mhiiLink = mhiiLink
        self.item_data = item_data or {"title": title, "subtitle": subtitle, "mhiiLink": mhiiLink}
        self._destroyed = False  # Track if widget is being destroyed

        self.setFixedSize(QSize(Metrics.GRID_ITEM_W, Metrics.GRID_ITEM_H))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._setupStyle()

        self.gridItemLayout = QVBoxLayout(self)
        self.gridItemLayout.setContentsMargins(10, 10, 10, 8)
        self.gridItemLayout.setSpacing(6)

        self.worker = None
        self._cancellation_token = None

        # Album art
        self.img_label = QLabel()
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setFixedSize(QSize(Metrics.GRID_ART_SIZE, Metrics.GRID_ART_SIZE))
        self.img_label.setStyleSheet(f"""
            border: none;
            background: {Colors.SURFACE_HOVER};
            border-radius: {Metrics.BORDER_RADIUS}px;
        """)
        self.gridItemLayout.addWidget(self.img_label)

        # Check for PC artwork first, then iPod artwork
        pc_art_hash = self.item_data.get("_pc_art_hash") if self.item_data else None
        if pc_art_hash:
            self._loadPCArtwork(pc_art_hash)
        elif mhiiLink is not None:
            self.loadImage()
        else:
            self._setPlaceholderImage()

        # Title
        self.title_label = ScrollingLabel(title)
        self.title_label.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.DemiBold))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title_label.setStyleSheet(f"border: none; background: transparent; color: {Colors.TEXT_PRIMARY};")
        self.title_label.setFixedHeight(20)
        self.gridItemLayout.addWidget(self.title_label)

        # Subtitle
        self.subtitle_label = ScrollingLabel(subtitle)
        self.subtitle_label.setFont(QFont(FONT_FAMILY, 9))
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.subtitle_label.setStyleSheet(f"border: none; background: transparent; color: {Colors.TEXT_SECONDARY};")
        self.subtitle_label.setFixedHeight(18)
        self.gridItemLayout.addWidget(self.subtitle_label)

    def _setupStyle(self):
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.SURFACE_ALT};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_XL}px;
                color: {Colors.TEXT_PRIMARY};
            }}
            QFrame:hover {{
                background-color: {Colors.SURFACE_HOVER};
                border: 1px solid {Colors.BORDER};
            }}
        """)

    def _setPlaceholderImage(self):
        """Set a placeholder when no artwork is available."""
        self.img_label.setText("♪")
        self.img_label.setFont(QFont(FONT_FAMILY, 40))
        from ..theme import ThemeManager
        a = ThemeManager.instance().accent
        self.img_label.setStyleSheet(f"""
            border: none;
            background: {a.rgba(35)};
            border-radius: {Metrics.BORDER_RADIUS}px;
            color: {Colors.TEXT_TERTIARY};
        """)

    def mousePressEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = a0.pos()
        super().mousePressEvent(a0)

    def mouseReleaseEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            # Only emit click if we didn't start a drag
            if hasattr(self, '_drag_start_pos') and self._drag_start_pos is not None:
                self.clicked.emit(self.item_data)
            self._drag_start_pos = None
        super().mouseReleaseEvent(a0)

    def mouseMoveEvent(self, a0):
        if not (a0.buttons() & Qt.MouseButton.LeftButton):
            return
        if not hasattr(self, '_drag_start_pos') or self._drag_start_pos is None:
            return
        if (a0.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return
        # Start drag
        self._drag_start_pos = None  # Prevent click on release
        drag = QDrag(self)
        mime = QMimeData()
        # Serialize item data for drop target
        drag_data = {
            "type": "grid_item",
            "title": self.item_data.get("title", ""),
            "category": self.item_data.get("category", ""),
            "filter_key": self.item_data.get("filter_key", ""),
            "filter_value": self.item_data.get("filter_value", ""),
            "artist": self.item_data.get("artist", ""),
            "album": self.item_data.get("album", ""),
        }
        mime.setData("application/x-iopenpod-items", json.dumps(drag_data).encode())
        mime.setText(self.item_data.get("title", ""))
        drag.setMimeData(mime)
        # Use artwork thumbnail as drag pixmap
        pm = self.img_label.pixmap()
        if pm and not pm.isNull():
            drag.setPixmap(pm.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
        drag.exec(Qt.DropAction.CopyAction)

    def cleanup(self):
        """Mark widget as destroyed and cancel any pending work."""
        log.debug(f"cleanup() called for item: {self.title_text}")
        self._destroyed = True
        if self.worker:
            log.debug(f"  Cancelling worker for: {self.title_text}")
            self.worker.cancel()
            try:
                self.worker.signals.result.disconnect(self._applyImage)
                log.debug(f"  Disconnected signal for: {self.title_text}")
            except (TypeError, RuntimeError) as e:
                log.debug(f"  Signal disconnect failed: {e}")
            self.worker = None

    def _loadPCArtwork(self, art_hash: str):
        """Load artwork from PC library art cache (thumbnail on disk)."""
        from ..pc_library_cache import get_pc_artwork
        pixmap = get_pc_artwork(art_hash)
        if pixmap and not pixmap.isNull():
            pixmap = pixmap.scaled(
                Metrics.GRID_ART_SIZE, Metrics.GRID_ART_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.img_label.setPixmap(pixmap)
            self.img_label.setStyleSheet(f"""
                border: none;
                background: transparent;
                border-radius: {Metrics.BORDER_RADIUS}px;
            """)
            # Compute dominant color for tinting and expander
            self._computePCColors(pixmap)
        else:
            self._setPlaceholderImage()

    def _computePCColors(self, pixmap: QPixmap):
        """Compute dominant color and album colors from a PC artwork pixmap."""
        try:
            from ..imgMaker import getDominantColor, getAlbumColors
            # Convert QPixmap to PIL Image for color analysis
            qimage = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            width, height = qimage.width(), qimage.height()
            ptr = qimage.bits()
            ptr.setsize(width * height * 4)
            from PIL import Image
            pil_image = Image.frombytes("RGBA", (width, height), bytes(ptr))
            dcol = getDominantColor(pil_image)
            album_colors = getAlbumColors(pil_image)

            if dcol:
                self.item_data["dominant_color"] = dcol
                r, g, b = dcol
                self.setStyleSheet(f"""
                    QFrame {{
                        background-color: rgba({r}, {g}, {b}, 30);
                        border: 1px solid rgba({r}, {g}, {b}, 25);
                        border-radius: {Metrics.BORDER_RADIUS_XL}px;
                        color: {Colors.TEXT_PRIMARY};
                    }}
                    QFrame:hover {{
                        background-color: rgba({r}, {g}, {b}, 55);
                        border: 1px solid rgba({r}, {g}, {b}, 45);
                    }}
                """)
            if album_colors:
                self.item_data["album_colors"] = album_colors
        except Exception as e:
            log.debug("PC color computation failed: %s", e)

    def loadImage(self):
        from ..app import Worker, ThreadPoolSingleton, DeviceManager
        log.debug(f"loadImage() called for: {self.title_text}, mhiiLink={self.mhiiLink}")

        if self.worker:
            log.debug(f"  Cancelling previous worker for: {self.title_text}")
            self.worker.cancel()

        self._cancellation_token = DeviceManager.get_instance().cancellation_token

        self.worker = Worker(self._loadImageData, self.mhiiLink)
        self.worker.signals.result.connect(self._applyImage)
        ThreadPoolSingleton.get_instance().start(self.worker)
        log.debug(f"  Worker started for: {self.title_text}")

    def _loadImageData(self, mhiiLink):
        """Load image data in worker thread."""
        from ..app import DeviceManager
        import os

        device = DeviceManager.get_instance()

        if device.cancellation_token.is_cancelled():
            return None

        if not device.device_path:
            return None

        artworkdb_path = device.artworkdb_path
        artwork_folder = device.artwork_folder_path

        if not artworkdb_path or not os.path.exists(artworkdb_path):
            return None

        if device.cancellation_token.is_cancelled():
            return None

        artworkdb_data, imgid_index = get_artworkdb_cached(artworkdb_path)

        if device.cancellation_token.is_cancelled():
            return None

        result = find_image_by_imgId(artworkdb_data, artwork_folder, mhiiLink, imgid_index)

        if result is None:
            return {"error": True, "mhiiLink": mhiiLink}

        pil_image, dcol = result

        # Compute full album colors (bg + text) in the worker thread
        album_colors = None
        if pil_image and dcol:
            try:
                from ..imgMaker import getAlbumColors
                album_colors = getAlbumColors(pil_image)
            except Exception:
                pass

        return {"pil_image": pil_image, "dcol": dcol, "album_colors": album_colors}

    def _applyImage(self, result):
        """Apply loaded image data on main thread."""
        log.debug(f"_applyImage() called for: {self.title_text}, destroyed={self._destroyed}")

        # Check if widget was destroyed while loading
        if self._destroyed:
            log.debug(f"  Widget destroyed, skipping: {self.title_text}")
            return

        try:
            # Additional safety check
            if not self.isVisible() and not self.parent():
                log.debug(f"  Widget not visible/no parent, skipping: {self.title_text}")
                return
        except RuntimeError as e:
            log.debug(f"  RuntimeError checking visibility: {e}")
            return

        from ..app import DeviceManager

        current_token = DeviceManager.get_instance().cancellation_token
        if self._cancellation_token is not current_token:
            log.debug(f"  Cancellation token mismatch, skipping: {self.title_text}")
            return

        log.debug(f"  Applying image for: {self.title_text}, result={result is not None}")

        if result is None or result.get("error"):
            self._setPlaceholderImage()
            return

        pil_image = result.get("pil_image")
        dcol = result.get("dcol")

        if pil_image is not None:
            # Convert PIL image to QPixmap safely by copying the data
            # ImageQt can cause crashes if PIL image goes out of scope
            pil_image = pil_image.convert("RGBA")
            data = pil_image.tobytes("raw", "RGBA")
            qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888)
            # Copy the QImage to own the data (prevents crash when data goes out of scope)
            qimage = qimage.copy()
            pixmap = QPixmap.fromImage(qimage)
            pixmap = pixmap.scaled(
                Metrics.GRID_ART_SIZE, Metrics.GRID_ART_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.img_label.setPixmap(pixmap)
            self.img_label.setStyleSheet(f"""
                border: none;
                background: transparent;
                border-radius: {Metrics.BORDER_RADIUS}px;
            """)

            # Store dominant color and full album colors for downstream use
            if dcol:
                self.item_data["dominant_color"] = dcol
                album_colors = result.get("album_colors")
                if album_colors:
                    self.item_data["album_colors"] = album_colors

            # Tint background with dominant color
            if dcol:
                r, g, b = dcol
                self.setStyleSheet(f"""
                    QFrame {{
                        background-color: rgba({r}, {g}, {b}, 30);
                        border: 1px solid rgba({r}, {g}, {b}, 25);
                        border-radius: {Metrics.BORDER_RADIUS_XL}px;
                        color: {Colors.TEXT_PRIMARY};
                    }}
                    QFrame:hover {{
                        background-color: rgba({r}, {g}, {b}, 55);
                        border: 1px solid rgba({r}, {g}, {b}, 45);
                    }}
                """)
