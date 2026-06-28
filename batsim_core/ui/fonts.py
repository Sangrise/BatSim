"""Application font setup helpers."""
from __future__ import annotations

import os

from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication


def setup_application_font(app: QApplication) -> None:
    """Load common Windows fonts explicitly for offscreen renders.

    PyQt's offscreen platform can fail to discover system fonts, which
    makes labels render as placeholder squares in generated manual
    screenshots. Loading known OS fonts also gives the live app a stable
    Korean/English fallback.
    """
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for name in ("malgun.ttf", "arial.ttf", "consola.ttf"):
        path = os.path.join(fonts_dir, name)
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)
    families = set(QFontDatabase.families())
    if "Malgun Gothic" in families:
        app.setFont(QFont("Malgun Gothic", 9))
    elif "Arial" in families:
        app.setFont(QFont("Arial", 9))
