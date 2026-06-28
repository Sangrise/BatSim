"""Application stylesheet."""
from __future__ import annotations

from PyQt6.QtWidgets import QApplication


APP_STYLE = """
QMainWindow, QDialog {
    background: #e9ecef;
    color: #1c2428;
}
QMenuBar, QMenu, QToolBar {
    background: #f7f8f9;
    color: #1c2428;
    border: none;
}
QToolBar {
    border-bottom: 1px solid #c8d0d5;
    spacing: 4px;
    padding: 3px;
}
QToolButton, QPushButton {
    background: #ffffff;
    border: 1px solid #aeb9c0;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 20px;
}
QToolButton:hover, QPushButton:hover {
    border-color: #4f8f7a;
    background: #f2fbf6;
}
QToolButton:pressed, QPushButton:pressed {
    background: #dcefe5;
}
QDockWidget {
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}
QDockWidget::title {
    background: #d8dee3;
    color: #1c2428;
    padding: 5px 7px;
    border-bottom: 1px solid #b8c2c9;
    font-weight: 600;
}
QLineEdit, QComboBox, QTreeWidget, QListWidget {
    background: #ffffff;
    color: #1c2428;
    border: 1px solid #b8c2c9;
    border-radius: 3px;
    selection-background-color: #2f6f59;
    selection-color: #ffffff;
}
QLineEdit, QComboBox {
    min-height: 22px;
    padding: 2px 5px;
}
QTabWidget::pane {
    border: 1px solid #b8c2c9;
    background: #ffffff;
}
QTabBar::tab {
    background: #d8dee3;
    color: #1c2428;
    padding: 5px 9px;
    border: 1px solid #b8c2c9;
    border-bottom: none;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #12372d;
}
QListWidget::item {
    padding: 3px 5px;
}
QListWidget::item:disabled {
    color: #526067;
    background: #eef1f3;
    font-weight: 600;
}
QTreeWidget::item {
    padding: 2px 4px;
}
QLabel#paletteHint {
    color: #526067;
    font-size: 11px;
}
QStatusBar {
    background: #f7f8f9;
    color: #334147;
    border-top: 1px solid #c8d0d5;
}
"""


def apply_app_style(app: QApplication | None) -> None:
    if app is not None:
        app.setStyleSheet(APP_STYLE)
