"""Right-side parameter inspector for the selected component."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QFormLayout, QLineEdit, QComboBox,
                             QLabel, QVBoxLayout, QCheckBox, QHBoxLayout,
                             QPushButton, QFileDialog)

from batsim.plugins.registry import (BATTERY_MODELS, list_battery_models,
                                     list_cells)


class InspectorWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._title = QLabel("(no selection)")
        self._title.setStyleSheet("font-weight:bold;")
        self._layout.addWidget(self._title)
        self._form_host = QWidget()
        self._form = QFormLayout(self._form_host)
        self._layout.addWidget(self._form_host)
        self._layout.addStretch()
        self._comp = None

    def set_component(self, comp):
        self._comp = comp
        # Clear form
        while self._form.count():
            it = self._form.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if comp is None:
            self._title.setText("(no selection)")
            return
        self._title.setText(f"{comp.cid}  ({comp.kind})")

        # For batteries: add a "cell" picker on top to load params from data file.
        if comp.kind == "BATTERY":
            cells = [""] + list_cells()
            cell_box = QComboBox()
            cell_box.addItems(cells)
            current_cell = comp.params.get("cell", "")
            idx = cell_box.findText(current_cell)
            if idx >= 0:
                cell_box.setCurrentIndex(idx)
            cell_box.currentTextChanged.connect(self._apply_cell_preset)
            self._form.addRow("cell (preset)", cell_box)

        for key, val in comp.params.items():
            if key == "model" and comp.kind == "BATTERY":
                box = QComboBox()
                models = list_battery_models() or ["Thevenin"]
                for name in models:
                    box.addItem(name)
                idx = box.findText(str(val))
                if idx >= 0:
                    box.setCurrentIndex(idx)
                box.currentTextChanged.connect(
                    lambda v, k=key: self._update_param(k, v))
                self._form.addRow(key, box)
            elif key == "chemistry" and comp.kind == "BATTERY":
                from batsim.models.base import OCV_TABLES
                box = QComboBox()
                for name in OCV_TABLES.keys():
                    box.addItem(name)
                idx = box.findText(str(val))
                if idx >= 0:
                    box.setCurrentIndex(idx)
                box.currentTextChanged.connect(
                    lambda v, k=key: self._update_param(k, v))
                self._form.addRow(key, box)
            elif key == "mode" and comp.kind == "BUS":
                box = QComboBox()
                for name in ("Grid", "PLoad", "ILoad"):
                    box.addItem(name)
                idx = box.findText(str(val))
                if idx >= 0:
                    box.setCurrentIndex(idx)
                box.currentTextChanged.connect(
                    lambda v, k=key: self._update_param(k, v))
                self._form.addRow(key, box)
            elif key == "mode" and comp.kind == "PCS":
                box = QComboBox()
                for name in ("V_DC", "I_DC", "P_DC",
                             "CC", "CV", "CP", "CCCV", "CPCV", "CYCLE"):
                    box.addItem(name)
                idx = box.findText(str(val))
                if idx >= 0:
                    box.setCurrentIndex(idx)
                box.currentTextChanged.connect(
                    lambda v, k=key: self._update_param(k, v))
                self._form.addRow(key, box)
            elif isinstance(val, bool):
                cb = QCheckBox()
                cb.setChecked(val)
                cb.toggled.connect(lambda v, k=key: self._update_param(k, v))
                self._form.addRow(key, cb)
            elif isinstance(val, (list, dict)):
                # Show as read-only repr; data-driven params edited via JSON file
                edit = QLineEdit(repr(val))
                edit.setReadOnly(True)
                self._form.addRow(key, edit)
            elif key in ("csv",) or (isinstance(val, str) and key.endswith("_csv")):
                row = QWidget()
                hl = QHBoxLayout(row)
                hl.setContentsMargins(0, 0, 0, 0)
                edit = QLineEdit(str(val))
                btn = QPushButton("…")
                btn.setFixedWidth(28)

                def _browse(_=None, e=edit, k=key):
                    path, _flt = QFileDialog.getOpenFileName(
                        self, "Select pattern CSV", "",
                        "CSV files (*.csv);;All files (*.*)")
                    if path:
                        e.setText(path)
                        self._update_param(k, path)
                        # Drop any cached waveform so the new file is reloaded
                        if "_wf" in self._comp.params:
                            self._comp.params.pop("_wf", None)

                btn.clicked.connect(_browse)
                edit.editingFinished.connect(
                    lambda e=edit, k=key: (
                        self._update_param(k, e.text()),
                        self._comp.params.pop("_wf", None)))
                hl.addWidget(edit)
                hl.addWidget(btn)
                self._form.addRow(key, row)
            else:
                edit = QLineEdit(str(val))
                edit.editingFinished.connect(
                    lambda e=edit, k=key: self._update_param(k, e.text()))
                self._form.addRow(key, edit)

    def _apply_cell_preset(self, cell_name: str):
        if self._comp is None or not cell_name:
            return
        from batsim.plugins.registry import CELL_LIBRARY
        entry = CELL_LIBRARY.get(cell_name)
        if not entry:
            return
        self._comp.params["cell"] = cell_name
        if "model" in entry:
            self._comp.params["model"] = entry["model"]
        for k, v in entry.get("params", {}).items():
            self._comp.params[k] = v
        self._comp.update()
        self.set_component(self._comp)  # rebuild form

    def _update_param(self, key, value):
        if self._comp is None:
            return
        old = self._comp.params.get(key)
        if isinstance(old, bool):
            self._comp.params[key] = bool(value)
        elif isinstance(old, (int, float)):
            try:
                self._comp.params[key] = float(value)
            except (TypeError, ValueError):
                return
        else:
            self._comp.params[key] = value
        self._comp.update()
