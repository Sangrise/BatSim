"""Component palette: searchable drag source for schematic components."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import (QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QTabWidget, QVBoxLayout, QWidget)

from batsim_core.components.groups import grouped_catalog


class _PaletteList(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAlternatingRowColors(True)
        self.setUniformItemSizes(True)

    def startDrag(self, supportedActions):  # noqa: N802
        item = self.currentItem()
        if item is None:
            return
        kind = item.data(Qt.ItemDataRole.UserRole)
        if not kind:
            return
        mime = QMimeData()
        mime.setData(PaletteWidget.MIME, kind.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class PaletteWidget(QWidget):
    MIME = "application/x-batsim-component"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Search components...")
        self._filter.textChanged.connect(self._rebuild)
        self._tabs = QTabWidget()
        self._lists: dict[str, _PaletteList] = {}
        for level, label in (("basic", "Basic"), ("advanced", "Advanced"),
                             ("all", "All")):
            lst = _PaletteList()
            self._lists[level] = lst
            self._tabs.addTab(lst, label)

        hint = QLabel("Basic covers circuit, measurement, battery and power-conversion work.")
        hint.setWordWrap(True)
        hint.setObjectName("paletteHint")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addWidget(self._filter)
        layout.addWidget(self._tabs, 1)
        layout.addWidget(hint)
        self._rebuild()

    def mimeTypes(self):  # noqa: N802
        return [self.MIME]

    def _rebuild(self):
        text = self._filter.text().strip().lower()
        for level, lst in self._lists.items():
            lst.clear()
            for group in grouped_catalog(level):
                matches = []
                for item in group["items"]:
                    haystack = f"{item['kind']} {item['label']}".lower()
                    if text and text not in haystack:
                        continue
                    matches.append(item)
                if not matches:
                    continue
                header = QListWidgetItem(group["group"])
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                header.setData(Qt.ItemDataRole.UserRole, None)
                header.setData(Qt.ItemDataRole.AccessibleDescriptionRole, "section")
                lst.addItem(header)
                for item in matches:
                    row = QListWidgetItem(f"{item['kind']:<8} {item['label']}")
                    row.setToolTip(
                        f"{item['label']}\nKind: {item['kind']} · Pins: {item['pins']}")
                    row.setData(Qt.ItemDataRole.UserRole, item["kind"])
                    lst.addItem(row)

