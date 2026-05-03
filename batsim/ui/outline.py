"""Right-side outline (object browser) listing every component and wire.

Selecting an entry highlights the matching items on the canvas; selecting
items on the canvas highlights the matching tree rows. Updates whenever the
scene's ``graphChanged`` fires.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTreeWidget,
                             QTreeWidgetItem, QLineEdit)


class OutlineWidget(QWidget):
    def __init__(self, scene, parent=None):
        super().__init__(parent)
        self._scene = scene
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("필터 (id/kind 검색)…")
        self._filter.textChanged.connect(self._apply_filter)
        v.addWidget(self._filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Object"])
        self.tree.setSelectionMode(
            QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self._on_tree_select)
        v.addWidget(self.tree)
        self._suspend = False
        scene.graphChanged.connect(self.refresh)
        scene.selectionChanged.connect(self._on_scene_select)
        self.refresh()

    # ------------------------------------------------------------------ build
    def refresh(self) -> None:
        self._suspend = True
        try:
            self.tree.clear()
            comp_root = QTreeWidgetItem(["Components"])
            wire_root = QTreeWidgetItem(["Wires"])
            self.tree.addTopLevelItem(comp_root)
            self.tree.addTopLevelItem(wire_root)
            comp_root.setExpanded(True)
            wire_root.setExpanded(True)
            for c in list(self._scene._components):
                label = f"{c.cid}  ({c.kind})"
                it = QTreeWidgetItem([label])
                it.setData(0, Qt.ItemDataRole.UserRole, ("c", id(c)))
                comp_root.addChild(it)
            for w in list(self._scene._wires):
                label = (f"{w.a_comp.cid}.{w.a_pin}  ↔  "
                         f"{w.b_comp.cid}.{w.b_pin}")
                it = QTreeWidgetItem([label])
                it.setData(0, Qt.ItemDataRole.UserRole, ("w", id(w)))
                wire_root.addChild(it)
            self._apply_filter(self._filter.text())
            self._sync_selection_from_scene()
        finally:
            self._suspend = False

    # ------------------------------------------------------------------ select
    def _all_rows(self):
        for i in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(i)
            for j in range(root.childCount()):
                yield root.child(j)

    def _id_to_obj(self):
        out: dict[int, object] = {}
        for c in self._scene._components:
            out[id(c)] = c
        for w in self._scene._wires:
            out[id(w)] = w
        return out

    def _on_tree_select(self):
        if self._suspend:
            return
        self._suspend = True
        try:
            mapping = self._id_to_obj()
            self._scene.clearSelection()
            for it in self.tree.selectedItems():
                data = it.data(0, Qt.ItemDataRole.UserRole)
                if not data:
                    continue
                obj = mapping.get(data[1])
                if obj is not None:
                    obj.setSelected(True)
        finally:
            self._suspend = False

    def _on_scene_select(self):
        if self._suspend:
            return
        self._suspend = True
        try:
            self._sync_selection_from_scene()
        finally:
            self._suspend = False

    def _sync_selection_from_scene(self):
        sel_ids = {id(x) for x in self._scene.selectedItems()}
        for ch in self._all_rows():
            data = ch.data(0, Qt.ItemDataRole.UserRole)
            ch.setSelected(bool(data and data[1] in sel_ids))

    # ------------------------------------------------------------------ filter
    def _apply_filter(self, text: str) -> None:
        text = (text or "").strip().lower()
        for ch in self._all_rows():
            visible = (not text) or (text in ch.text(0).lower())
            ch.setHidden(not visible)
