"""F1 help dialog displaying the bundled HTML manual.

The manual is shipped in two languages.  The dialog auto-picks the file that
matches the system locale (Korean for ko*, English for everything else).
The user can switch language at any time, either with the toolbar buttons
or via the language switcher embedded inside the HTML.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from PyQt6.QtCore import Qt, QUrl, QLocale
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTextBrowser, QLabel)


HELP_DIR = Path(__file__).resolve().parents[2] / "assets" / "help"
MANUAL_FILES: dict[str, Path] = {
    "ko": HELP_DIR / "manual_ko.html",
    "en": HELP_DIR / "manual_en.html",
}
# Backwards-compat: some tests import MANUAL_PATH.  Point it at the default.
MANUAL_PATH = MANUAL_FILES["en"]

Lang = Literal["ko", "en"]


def detect_system_language() -> Lang:
    """Return 'ko' for Korean systems, otherwise 'en'."""
    name = QLocale.system().name()  # e.g. 'ko_KR', 'en_US', 'ja_JP'
    return "ko" if name.lower().startswith("ko") else "en"


class HelpDialog(QDialog):
    def __init__(self, parent=None, lang: Lang | None = None):
        super().__init__(parent)
        self._lang: Lang = lang or detect_system_language()

        self.setWindowTitle(self._title_for(self._lang))
        self.resize(900, 720)

        layout = QVBoxLayout(self)

        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(False)
        self.browser.setOpenLinks(False)
        self.browser.setSearchPaths([str(HELP_DIR)])
        # Catch clicks on the in-page language switcher / external links.
        self.browser.anchorClicked.connect(self._on_anchor)
        layout.addWidget(self.browser)

        bar = QHBoxLayout()
        self._path_label = QLabel("")
        self._path_label.setStyleSheet("color:#888; font-size:11px;")
        bar.addWidget(self._path_label, 1)

        self._btn_ko = QPushButton("한국어")
        self._btn_ko.setCheckable(True)
        self._btn_ko.clicked.connect(lambda: self.set_language("ko"))
        bar.addWidget(self._btn_ko)

        self._btn_en = QPushButton("English")
        self._btn_en.setCheckable(True)
        self._btn_en.clicked.connect(lambda: self.set_language("en"))
        bar.addWidget(self._btn_en)

        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self._load_manual)
        bar.addWidget(reload_btn)

        home_btn = QPushButton("Top")
        home_btn.clicked.connect(lambda: self.browser.scrollToAnchor(""))
        bar.addWidget(home_btn)

        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        bar.addWidget(close_btn)

        layout.addLayout(bar)

        QShortcut(QKeySequence("Escape"), self, activated=self.accept)

        self._load_manual()

    # -- helpers ------------------------------------------------------------
    def _title_for(self, lang: Lang) -> str:
        return "BatSim 매뉴얼  (F1)" if lang == "ko" else "BatSim Manual  (F1)"

    def _current_path(self) -> Path:
        return MANUAL_FILES[self._lang]

    def set_language(self, lang: Lang) -> None:
        if lang not in MANUAL_FILES:
            lang = "en"
        self._lang = lang
        self.setWindowTitle(self._title_for(lang))
        self._load_manual()

    def _on_anchor(self, url: QUrl) -> None:
        # In-document anchor (#section) → just scroll
        if url.scheme() in ("", "about") and not url.path() and url.hasFragment():
            self.browser.scrollToAnchor(url.fragment())
            return

        target = url.fileName() or url.path().rsplit("/", 1)[-1]
        if target == "manual_ko.html":
            self.set_language("ko")
            return
        if target == "manual_en.html":
            self.set_language("en")
            return
        # Fallback: open external links in a real browser
        if url.scheme() in ("http", "https", "mailto"):
            from PyQt6.QtGui import QDesktopServices
            QDesktopServices.openUrl(url)

    def _load_manual(self) -> None:
        # Sync language buttons
        self._btn_ko.setChecked(self._lang == "ko")
        self._btn_en.setChecked(self._lang == "en")

        path = self._current_path()
        self._path_label.setText(str(path))
        if path.exists():
            self.browser.setSearchPaths([str(HELP_DIR)])
            self.browser.setHtml(path.read_text(encoding="utf-8"))
        else:
            msg_ko = "<h2>매뉴얼을 찾을 수 없습니다</h2>"
            msg_en = "<h2>Manual not found</h2>"
            self.browser.setHtml(
                (msg_ko if self._lang == "ko" else msg_en)
                + f"<p><code>{path}</code></p>"
            )

    def jump(self, anchor: str) -> None:
        """Scroll to a section anchor (e.g. 'sim', 'cli')."""
        self.browser.scrollToAnchor(anchor)
