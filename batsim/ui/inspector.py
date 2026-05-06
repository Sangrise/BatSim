"""Right-side parameter inspector for the selected component."""
from __future__ import annotations

import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QFormLayout, QLineEdit, QComboBox,
                             QLabel, QVBoxLayout, QCheckBox, QHBoxLayout,
                             QPushButton, QFileDialog)

from batsim.plugins.registry import (BATTERY_MODELS, list_battery_models,
                                     list_cells)
from batsim.plugins import refresh_if_changed


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
        if comp.kind in ("BATTERY", "BATPACK", "BATRACK"):
            refresh_if_changed()
            cells = [""] + list_cells()
            cell_box = QComboBox()
            cell_box.addItems(cells)
            current_cell = comp.params.get("cell", "")
            idx = cell_box.findText(current_cell)
            if idx >= 0:
                cell_box.setCurrentIndex(idx)
            cell_box.currentTextChanged.connect(self._apply_cell_preset)
            self._form.addRow("cell (preset)", cell_box)

        # Mode-specific parameter visibility for PCS so the user only
        # sees fields that matter for the chosen mode.
        pcs_mode = comp.params.get("mode") if comp.kind == "PCS" else None
        pcs_visible: set[str] | None = None
        if pcs_mode is not None:
            base = {"mode", "eta"}
            relevant = {
                "V_DC": {"V_DC_set"},
                "I_DC": {"I_DC_set"},
                "P_DC": {"P_DC_set"},
                "CC":   {"I_set"},
                "CV":   {"V_set"},
                "CP":   {"P_set"},
                "CCCV": {"I_set", "V_max", "V_min", "I_term", "n_series"},
                "CPCV": {"P_set", "V_max", "V_min", "I_term", "n_series"},
                "CYCLE_SIMPLE": {"cyc_I_chg", "cyc_I_dis", "cyc_V_max",
                                 "cyc_V_min", "cyc_t_rest",
                                 "cyc_count", "n_series"},
                "CYCLE": {"cycle_steps", "cycle_repeat", "n_series"},
            }.get(pcs_mode, set())
            pcs_visible = base | relevant

        for key, val in comp.params.items():
            # Hidden internal state (prefixed with "_") never shown.
            if key.startswith("_"):
                continue
            if pcs_visible is not None and key not in pcs_visible:
                continue
            if key == "model" and comp.kind in ("BATTERY", "BATPACK", "BATRACK"):
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
            elif key == "balancer" and comp.kind in ("BATPACK", "BATRACK", "BMS"):
                from batsim.bms.cell_balancer import list_balancers
                box = QComboBox()
                names = list_balancers()
                if comp.kind == "BMS":
                    # "Inherit" lets the BMS leave per-pack defaults alone.
                    names = ["Inherit"] + [n for n in names if n != "Inherit"]
                for name in names:
                    box.addItem(name)
                idx = box.findText(str(val))
                if idx >= 0:
                    box.setCurrentIndex(idx)
                box.currentTextChanged.connect(
                    lambda v, k=key: self._update_param(k, v))
                self._form.addRow(key, box)
            elif key == "chemistry" and comp.kind == "BATTERY":
                # Legacy parameter — chemistry presets removed.  Show as
                # read-only text so old project files still display sane.
                edit = QLineEdit(str(val))
                edit.setReadOnly(True)
                edit.setToolTip("Chemistry presets removed; use a 'cell' "
                                "(CSV folder) for real OCV data.")
                self._form.addRow(key, edit)
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
                # CYCLE first — the recommended cycler with table editor.
                # CYCLE_SIMPLE remains for users who prefer the legacy
                # 7-parameter charge-rest-discharge-rest cycler.
                for name in ("CYCLE", "CYCLE_SIMPLE",
                             "V_DC", "I_DC", "P_DC",
                             "CC", "CV", "CP", "CCCV", "CPCV"):
                    box.addItem(name)
                idx = box.findText(str(val))
                if idx >= 0:
                    box.setCurrentIndex(idx)
                box.currentTextChanged.connect(
                    lambda v, k=key: (self._update_param(k, v),
                                       self.set_component(self._comp)))
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
            elif key == "cycle_steps" and comp.kind == "PCS":
                # Open a step-table editor (PNE-cycler-style) instead of
                # forcing the user to hand-edit JSON.
                row = QWidget()
                hl = QHBoxLayout(row)
                hl.setContentsMargins(0, 0, 0, 0)
                preview = QLineEdit(str(val))
                preview.setReadOnly(True)
                btn = QPushButton("Edit…")
                btn.setFixedWidth(56)

                def _open_editor(_=None, e=preview):
                    from batsim.ui.pcs_cycle_dialog import CycleStepsDialog
                    raw = self._comp.params.get("cycle_steps", "[]")
                    try:
                        steps = raw if isinstance(raw, list) else json.loads(raw)
                    except Exception:
                        steps = []
                    dlg = CycleStepsDialog(
                        self, steps=steps,
                        repeat=int(self._comp.params.get("cycle_repeat", 1) or 1),
                        n_series=int(self._comp.params.get("n_series", 1) or 1))
                    if dlg.exec():
                        new_json = dlg.steps_json()
                        self._comp.params["cycle_steps"] = new_json
                        self._comp.params["cycle_repeat"] = dlg.repeat()
                        self._comp.params["n_series"] = dlg.n_series()
                        e.setText(new_json)
                        self.set_component(self._comp)

                btn.clicked.connect(_open_editor)
                hl.addWidget(preview, 1)
                hl.addWidget(btn)
                self._form.addRow(key, row)
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
