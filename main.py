import os
import sys
import logging
import traceback
from PyQt6.QtWidgets import QApplication, QMessageBox
from GUI.app import MainWindow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)


def _get_crash_log_path() -> str:
    """Get path for crash log file."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Logs")
    else:
        base = os.environ.get("XDG_STATE_HOME", os.path.join(os.path.expanduser("~"), ".local", "state"))

    log_dir = os.path.join(base, "iOpenPod")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "crash.log")


def global_exception_handler(exc_type, exc_value, exc_tb):
    """Global exception handler to catch unhandled exceptions.

    Logs the error, saves a crash report, and shows a user-friendly dialog
    instead of silently crashing.
    """
    # Don't catch keyboard interrupt
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    # Format the traceback
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
    tb_text = "".join(tb_lines)

    # Log to file
    crash_log_path = _get_crash_log_path()
    try:
        from datetime import datetime
        with open(crash_log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 60}\n")
            f.write(f"Crash at {datetime.now().isoformat()}\n")
            f.write(f"{'=' * 60}\n")
            f.write(tb_text)
            f.write("\n")
    except Exception:
        pass  # Don't fail while handling failure

    # Log to console
    logger.critical(f"Unhandled exception: {exc_type.__name__}: {exc_value}")
    logger.critical(tb_text)

    # Show user-friendly dialog if Qt app is running
    try:
        app = QApplication.instance()
        if app:
            error_msg = (
                f"An unexpected error occurred:\n\n"
                f"{exc_type.__name__}: {exc_value}\n\n"
                f"A crash report has been saved to:\n{crash_log_path}\n\n"
                f"Please report this issue on GitHub."
            )
            QMessageBox.critical(None, "iOpenPod Error", error_msg)
    except Exception:
        pass  # Don't fail while handling failure


# Install global exception handler
sys.excepthook = global_exception_handler


def run_pyqt_app():
    app = QApplication([])

    # Register bundled Noto fonts so the UI renders correctly on systems
    # that lack them (e.g. Fedora Silverblue, minimal Linux installs).
    from GUI.fonts import load_bundled_fonts
    load_bundled_fonts()

    # Use custom proxy style for scrollbars (CSS scrollbar styling is
    # unreliable on Windows with Fusion — this paints them directly).
    from GUI.styles import DarkScrollbarStyle
    app.setStyle(DarkScrollbarStyle("Fusion"))

    # Initialize ThemeManager with saved settings, then apply palette +
    # stylesheet in one shot.  This replaces the old hardcoded QPalette
    # and APP_STYLESHEET constant.
    from GUI.theme import ThemeManager
    from GUI.settings import get_settings

    settings = get_settings()
    tm = ThemeManager.instance()
    tm.set_accent(settings.accent_color)
    tm.set_mode(settings.theme_mode)
    tm.apply_initial()

    window = MainWindow()

    window.show()

    # Start the event loop
    app.exec()
    print("App closed")


if __name__ == "__main__":
    run_pyqt_app()
