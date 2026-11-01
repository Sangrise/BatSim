"""Application stylesheet."""
from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication


APP_STYLE = """
QWidget {
    background: #16191c;
    color: #e8ecef;
}
QMainWindow, QDialog, QMessageBox, QFileDialog, QInputDialog {
    background: #16191c;
    color: #e8ecef;
}
QMenuBar, QMenu, QToolBar {
    background: #1f2428;
    color: #e8ecef;
    border: none;
}
QToolBar {
    border-bottom: 1px solid #303840;
    spacing: 4px;
    padding: 3px;
}
QToolButton, QPushButton {
    background: #252b30;
    color: #f4f7f9;
    border: 1px solid #45515a;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 20px;
}
QToolButton:hover, QPushButton:hover {
    border-color: #6eb79d;
    background: #2e3b3a;
}
QToolButton:pressed, QPushButton:pressed {
    background: #20312d;
}
QToolButton:disabled, QPushButton:disabled {
    background: #202428;
    color: #78838a;
    border-color: #303840;
}
QMenu::item {
    color: #e8ecef;
    padding: 4px 22px;
}
QMenu::item:selected {
    background: #2f6f59;
    color: #ffffff;
}
QDockWidget {
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}
QDockWidget::title {
    background: #22282d;
    color: #f4f7f9;
    padding: 5px 7px;
    border-bottom: 1px solid #303840;
    font-weight: 600;
}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox,
QComboBox, QTreeWidget, QTableWidget, QListWidget, QTextBrowser {
    background: #0f1214;
    color: #e8ecef;
    border: 1px solid #3a444c;
    border-radius: 3px;
    selection-background-color: #2f6f59;
    selection-color: #ffffff;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 22px;
    padding: 2px 5px;
}
QComboBox QAbstractItemView {
    background: #0f1214;
    color: #e8ecef;
    border: 1px solid #3a444c;
    selection-background-color: #2f6f59;
}
QHeaderView::section {
    background: #252b30;
    color: #f4f7f9;
    border: 1px solid #3a444c;
    padding: 4px;
}
QTabWidget::pane {
    border: 1px solid #3a444c;
    background: #16191c;
}
QTabBar::tab {
    background: #252b30;
    color: #d5dce1;
    padding: 5px 9px;
    border: 1px solid #3a444c;
    border-bottom: none;
}
QTabBar::tab:selected {
    background: #16191c;
    color: #ffffff;
}
QListWidget::item {
    padding: 3px 5px;
}
QListWidget::item:disabled {
    color: #9aa7af;
    background: #202428;
    font-weight: 600;
}
QTreeWidget::item {
    padding: 2px 4px;
}
QLabel#paletteHint {
    color: #aeb8bf;
    font-size: 11px;
}
QStatusBar {
    background: #1f2428;
    color: #d5dce1;
    border-top: 1px solid #303840;
}
QSplitter::handle {
    background: #303840;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background: #16191c;
    border: none;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #45515a;
    border-radius: 3px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    background: none;
    border: none;
}
"""


def apply_app_style(app: QApplication | None) -> None:
    if app is not None:
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#16191c"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#e8ecef"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#0f1214"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#1f2428"))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#252b30"))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f4f7f9"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#e8ecef"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#252b30"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f4f7f9"))
        palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#2f6f59"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#78838a"))
        app.setPalette(palette)
        app.setStyleSheet(APP_STYLE)
