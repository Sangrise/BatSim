"""Component palette: drag source on the left side of the main window."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import QListWidget, QListWidgetItem

from batsim.components.catalog import CATALOG


class PaletteWidget(QListWidget):
    MIME = "application/x-batsim-component"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        for kind, spec in CATALOG.items():
            item = QListWidgetItem(f"{spec['label']}  [{kind}]")
            item.setData(Qt.ItemDataRole.UserRole, kind)
            self.addItem(item)

    def mimeTypes(self):  # noqa: N802
        return [self.MIME]

    def startDrag(self, supportedActions):  # noqa: N802
        item = self.currentItem()
        if item is None:
            return
        kind = item.data(Qt.ItemDataRole.UserRole)
        mime = QMimeData()
        mime.setData(self.MIME, kind.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)
