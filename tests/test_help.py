"""Help dialog smoke tests (creates a QApplication if needed)."""
import sys
from pathlib import Path

import pytest


def test_manual_html_files_exist():
    base = Path(__file__).parents[1] / "assets" / "help"
    ko = base / "manual_ko.html"
    en = base / "manual_en.html"
    assert ko.exists() and en.exists()
    ko_text = ko.read_text(encoding="utf-8")
    en_text = en.read_text(encoding="utf-8")
    # Korean version
    assert "BatSim 사용자 매뉴얼" in ko_text
    assert 'id="cli"' in ko_text
    # English version
    assert "BatSim User Manual" in en_text
    assert 'id="extend"' in en_text
    # Both contain language switcher links
    for t in (ko_text, en_text):
        assert "manual_ko.html" in t and "manual_en.html" in t


def test_detect_system_language_returns_known_value():
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from batsim_core.ui.help_dialog import detect_system_language
    lang = detect_system_language()
    assert lang in ("ko", "en")


def test_help_dialog_loads_default_locale():
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from batsim_core.ui.help_dialog import HelpDialog
    dlg = HelpDialog()
    assert len(dlg.browser.toPlainText()) > 100
    dlg.close()


def test_help_dialog_can_switch_language():
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from batsim_core.ui.help_dialog import HelpDialog
    dlg = HelpDialog(lang="en")
    assert "BatSim Manual" in dlg.windowTitle()
    text_en = dlg.browser.toPlainText()
    dlg.set_language("ko")
    assert "매뉴얼" in dlg.windowTitle()
    text_ko = dlg.browser.toPlainText()
    assert text_en != text_ko
    assert "사용자 매뉴얼" in text_ko
    dlg.close()


def test_main_window_has_f1_help():
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    import batsim_core.plugins.builtin  # noqa: F401
    from batsim_core.plugins import discover
    discover()
    from batsim_core.ui.main_window import MainWindow
    win = MainWindow()
    win.show_help()
    assert win._help_dialog is not None
    win._help_dialog.close()
    win.close()


