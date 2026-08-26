import os
import sys
from pathlib import Path

# Setup paths - Portable root
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app import TTSMainWindow


def main():
    # Enable High DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("TTSx Studio")
    app.setOrganizationName("TTSx")

    # Set App Icon from local assets
    for icon_name in ("ttsx.ico", "ttsx.png", "app_logo.ico", "app_logo.png", "capcap.ico", "capcap.png"):
        icon_path = APP_DIR / "assets" / icon_name
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
            break

    window = TTSMainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
