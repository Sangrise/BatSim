"""PCS cycle step editor — a PNE-cycler-style table for the CYCLE mode.

The dialog presents the user with a simple table where each row is one
step.  Columns:

  Type        — Charge | Discharge | Rest | Charge (V) | Discharge (V)
  Value       — magnitude (W for power steps, A for current steps,
                V for CV steps, ignored for Rest)
  Unit        — A | W | V (auto from Type, displayed as label)
  V_max (V)   — charging cut-off voltage  (blank = no V limit)
  V_min (V)   — discharging cut-off voltage (blank = no V limit)
  I_term (A)  — taper current cut-off    (blank = no I_term)
  Time (s)    — max time for the step    (blank = no time limit)

Internally the dialog converts to / from the existing ``cycle_steps``
JSON list consumed by ``engine.pcs_control``.  Sign convention:

  Charge        → CC step with I = +|value|
  Discharge     → CC step with I = -|value|
  Charge (P)    → CP step with P = +|value|
  Discharge (P) → CP step with P = -|value|
  Charge (V)    → CV step with V = value (for taper / hold)
  Rest          → REST step
"""
from __future__ import annotations

import json
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QPushButton, QLabel, QComboBox,
                             QDialogButtonBox, QSpinBox, QHeaderView, QWidget)


# Column indices for the table.
COL_TYPE = 0
COL_VALUE = 1
COL_VMAX = 2
COL_VMIN = 3
COL_ITERM = 4
COL_TIME = 5
N_COLS = 6

TYPES = [
    "Charge (CC)",      # CC,  I = +|val|, A
    "Discharge (CC)",   # CC,  I = -|val|, A
    "Charge (CP)",      # CP,  P = +|val|, W
    "Discharge (CP)",   # CP,  P = -|val|, W
    "Charge (CV)",      # CV,  V = val,    V
    "Rest",             # REST
]


def _step_to_row(step: dict) -> dict:
    """Convert one engine step dict → row form."""
    sm = str(step.get("mode", "REST")).upper()
    # V_max/V_min may be stored either as pack-level (V_max/V_min) or
    # per-cell (V_max_cell/V_min_cell).  Either is rendered in the same
    # column; the dialog tracks which form to write back via the global
    # "Per-cell V limits" checkbox.
    v_max = step.get("V_max_cell", step.get("V_max", ""))
    v_min = step.get("V_min_cell", step.get("V_min", ""))
    row: dict[str, Any] = {
        "type": "Rest",
        "value": "",
        "v_max": v_max,
        "v_min": v_min,
        "i_term": step.get("I_term", ""),
        "time": step.get("max_time", step.get("time", "")),
    }
    if sm == "CC":
        I = float(step.get("I", 0.0))
        row["type"] = "Charge (CC)" if I >= 0 else "Discharge (CC)"
        row["value"] = abs(I)
    elif sm == "CP":
        P = float(step.get("P", 0.0))
        row["type"] = "Charge (CP)" if P >= 0 else "Discharge (CP)"
        row["value"] = abs(P)
    elif sm == "CV":
        row["type"] = "Charge (CV)"
        row["value"] = float(step.get("V", 0.0))
    elif sm == "REST":
        row["type"] = "Rest"
    return row


def _row_to_step(row: dict, per_cell_v: bool = False) -> dict:
    """Convert one row dict → engine step dict.

    When ``per_cell_v`` is True, V_max / V_min columns are saved as
    ``V_max_cell`` / ``V_min_cell`` so the engine multiplies them by the
    PCS ``n_series`` parameter at runtime."""
    t = str(row.get("type", "Rest"))
    out: dict[str, Any] = {}
    val = row.get("value", "")
    try:
        v = float(val) if val not in ("", None) else 0.0
    except (TypeError, ValueError):
        v = 0.0
    if t == "Charge (CC)":
        out["mode"] = "CC"; out["I"] = abs(v)
    elif t == "Discharge (CC)":
        out["mode"] = "CC"; out["I"] = -abs(v)
    elif t == "Charge (CP)":
        out["mode"] = "CP"; out["P"] = abs(v)
    elif t == "Discharge (CP)":
        out["mode"] = "CP"; out["P"] = -abs(v)
    elif t == "Charge (CV)":
        out["mode"] = "CV"; out["V"] = v
    else:
        out["mode"] = "REST"

    # Optional terminators.  Empty string = not set.
    v_max_key = "V_max_cell" if per_cell_v else "V_max"
    v_min_key = "V_min_cell" if per_cell_v else "V_min"
    for key, src in ((v_max_key, "v_max"), (v_min_key, "v_min"),
                     ("I_term", "i_term"), ("max_time", "time")):
        s = row.get(src, "")
        if s in ("", None):
            continue
        try:
            out[key] = float(s)
        except (TypeError, ValueError):
            continue
    return out


class CycleStepsDialog(QDialog):
    """Table editor for PCS CYCLE step list."""

    def __init__(self, parent=None, steps: list | None = None,
                 repeat: int = 1, n_series: int = 1):
        super().__init__(parent)
        self.setWindowTitle("Cycle Steps Editor")
        self.resize(880, 480)

        v = QVBoxLayout(self)

        info = QLabel(
            "각 행은 한 단계입니다. 종료 조건(전압 / 전류 / 시간) 중 "
            "하나라도 만족하면 다음 단계로 넘어갑니다. 빈 칸은 "
            "‘조건 없음’을 뜻합니다.")
        info.setWordWrap(True)
        info.setStyleSheet("color:#888;")
        v.addWidget(info)

        # Top bar: per-cell V toggle + N series spinner
        opt = QHBoxLayout()
        from PyQt6.QtWidgets import QCheckBox
        self.per_cell_chk = QCheckBox("V limits are per-cell  (×N series)")
        self.per_cell_chk.setToolTip(
            "체크하면 V_max / V_min 컬럼에 입력한 값을 셀 단위로 해석하고, "
            "런타임에 N series 를 곱해 팩 임계전압으로 변환합니다.")
        opt.addWidget(self.per_cell_chk)
        opt.addSpacing(12)
        opt.addWidget(QLabel("N series:"))
        self.n_series_spin = QSpinBox()
        self.n_series_spin.setRange(1, 9999)
        self.n_series_spin.setValue(int(n_series) if n_series else 1)
        opt.addWidget(self.n_series_spin)
        opt.addStretch(1)
        v.addLayout(opt)

        self.table = QTableWidget(0, N_COLS, self)
        self.table.setHorizontalHeaderLabels([
            "Type", "Value (A/W/V)", "V_max", "V_min",
            "I_term (A)", "Time (s)"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.table, 1)

        # Toolbar — add / remove / move up / move down + repeat count
        bar = QHBoxLayout()
        b_add = QPushButton("+ Add step")
        b_rem = QPushButton("− Remove")
        b_up = QPushButton("↑ Up")
        b_dn = QPushButton("↓ Down")
        b_add.clicked.connect(lambda: self._add_row({}))
        b_rem.clicked.connect(self._remove_selected)
        b_up.clicked.connect(lambda: self._move_selected(-1))
        b_dn.clicked.connect(lambda: self._move_selected(+1))
        for w in (b_add, b_rem, b_up, b_dn):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(QLabel("Repeat:"))
        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(0, 9999)
        self.repeat_spin.setValue(int(repeat) if repeat is not None else 1)
        self.repeat_spin.setToolTip("Number of times to repeat the entire "
                                    "cycle list. 0 = run forever (use the "
                                    "simulation t_end to stop).")
        bar.addWidget(self.repeat_spin)
        v.addLayout(bar)

        # OK / Cancel
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

        # Auto-detect per-cell mode from incoming steps.
        any_per_cell = any(isinstance(s, dict)
                           and ("V_max_cell" in s or "V_min_cell" in s)
                           for s in (steps or []))
        self.per_cell_chk.setChecked(any_per_cell)
        self.per_cell_chk.toggled.connect(self._refresh_v_headers)
        self._refresh_v_headers(any_per_cell)

        # Pre-populate
        for s in (steps or []):
            self._add_row(_step_to_row(s if isinstance(s, dict) else {}))
        if not steps:
            # Provide one charge + one rest + one discharge + one rest as a
            # ready-to-tweak example.
            self._add_row({"type": "Charge (CC)", "value": 10,
                           "v_max": 4.2, "time": 3600})
            self._add_row({"type": "Rest", "time": 600})
            self._add_row({"type": "Discharge (CC)", "value": 10,
                           "v_min": 3.0, "time": 3600})
            self._add_row({"type": "Rest", "time": 600})

    def _refresh_v_headers(self, per_cell: bool) -> None:
        unit = "V/cell" if per_cell else "V"
        self.table.setHorizontalHeaderItem(
            COL_VMAX, QTableWidgetItem(f"V_max ({unit})"))
        self.table.setHorizontalHeaderItem(
            COL_VMIN, QTableWidgetItem(f"V_min ({unit})"))

    # ------------------------------------------------------------------
    # Row helpers
    # ------------------------------------------------------------------
    def _add_row(self, row: dict) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        # Type combobox
        cb = QComboBox()
        cb.addItems(TYPES)
        cb.setCurrentText(str(row.get("type", "Rest")))
        self.table.setCellWidget(r, COL_TYPE, cb)
        for col, key in ((COL_VALUE, "value"),
                         (COL_VMAX, "v_max"),
                         (COL_VMIN, "v_min"),
                         (COL_ITERM, "i_term"),
                         (COL_TIME, "time")):
            val = row.get(key, "")
            it = QTableWidgetItem(str(val) if val not in ("", None) else "")
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, col, it)

    def _remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()},
                      reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def _move_selected(self, delta: int) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            return
        if delta < 0 and rows[0] == 0:
            return
        if delta > 0 and rows[-1] == self.table.rowCount() - 1:
            return
        # Capture row data, pop, re-insert at new index.  Single-row only
        # for simplicity.
        r = rows[0]
        row_data = self._read_row(r)
        self.table.removeRow(r)
        new_r = r + delta
        self.table.insertRow(new_r)
        cb = QComboBox(); cb.addItems(TYPES)
        cb.setCurrentText(row_data["type"])
        self.table.setCellWidget(new_r, COL_TYPE, cb)
        for col, key in ((COL_VALUE, "value"),
                         (COL_VMAX, "v_max"),
                         (COL_VMIN, "v_min"),
                         (COL_ITERM, "i_term"),
                         (COL_TIME, "time")):
            val = row_data.get(key, "")
            it = QTableWidgetItem(str(val) if val not in ("", None) else "")
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(new_r, col, it)
        self.table.selectRow(new_r)

    def _read_row(self, r: int) -> dict:
        cb = self.table.cellWidget(r, COL_TYPE)
        out = {"type": cb.currentText() if cb else "Rest"}
        for col, key in ((COL_VALUE, "value"),
                         (COL_VMAX, "v_max"),
                         (COL_VMIN, "v_min"),
                         (COL_ITERM, "i_term"),
                         (COL_TIME, "time")):
            it = self.table.item(r, col)
            out[key] = it.text().strip() if it else ""
        return out

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------
    def steps_json(self) -> str:
        """Return the steps as a JSON string ready to assign to
        ``cycle_steps``."""
        per_cell = self.per_cell_chk.isChecked()
        steps = []
        for r in range(self.table.rowCount()):
            steps.append(_row_to_step(self._read_row(r), per_cell_v=per_cell))
        return json.dumps(steps)

    def repeat(self) -> int:
        return int(self.repeat_spin.value())

    def n_series(self) -> int:
        return int(self.n_series_spin.value())
