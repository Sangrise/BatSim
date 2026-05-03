"""Simulation configuration dialog."""
from __future__ import annotations

import json

from PyQt6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QDialogButtonBox,
                             QComboBox, QLabel, QPushButton, QHBoxLayout,
                             QWidget)


def _estimate_pcs_total_time(netlist) -> float | None:
    """Sum of cycle step durations × cycle_repeat across all PCS elements.

    Returns the maximum among all PCS components (so t_end covers them
    all), or None if none specifies a finite cycle."""
    if netlist is None:
        return None
    best = 0.0
    found = False
    for c in getattr(netlist, "components", []) or []:
        if c.get("kind") != "PCS":
            continue
        params = c.get("params", {})
        mode = params.get("mode", "")
        if mode != "CYCLE":
            continue
        raw = params.get("cycle_steps", "[]")
        try:
            steps = raw if isinstance(raw, list) else json.loads(raw)
        except Exception:
            continue
        total = 0.0
        for s in steps:
            t = s.get("max_time") or s.get("time") or 0.0
            try:
                total += float(t)
            except Exception:
                pass
        repeat = int(params.get("cycle_repeat", 1) or 1)
        if repeat <= 0:
            continue  # infinite — user must set t_end manually
        total *= repeat
        if total > 0:
            found = True
            best = max(best, total)
    return best if found else None


class SimulationDialog(QDialog):
    def __init__(self, parent=None, netlist=None):
        super().__init__(parent)
        self.setWindowTitle("Run Simulation")
        self._netlist = netlist
        layout = QFormLayout(self)
        self.kind = QComboBox()
        self.kind.addItems(["Transient", "DC operating point"])
        self.kind.currentTextChanged.connect(self._on_kind_changed)

        self._kind_help = QLabel()
        self._kind_help.setWordWrap(True)
        self._kind_help.setStyleSheet("color: #555; font-size: 11px;")

        self.t_end = QLineEdit("1.0")
        self.dt = QLineEdit("0.001")

        # "Use PCS cycle length" helper button
        t_end_row = QWidget()
        h = QHBoxLayout(t_end_row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.t_end, 1)
        self._cycle_btn = QPushButton("Auto from PCS cycle")
        self._cycle_btn.setToolTip(
            "Compute t_end from PCS cycle steps (sum × cycle_repeat).\n"
            "PCS cycles describe WHAT to do; t_end limits HOW LONG\n"
            "to simulate. They are independent — if t_end < cycle\n"
            "duration, the simulation stops early; if larger, the PCS\n"
            "stays in DONE state after the cycle finishes.")
        self._cycle_btn.clicked.connect(self._fill_from_cycle)
        h.addWidget(self._cycle_btn)

        layout.addRow("Type", self.kind)
        layout.addRow("", self._kind_help)
        layout.addRow("t_end (s)", t_end_row)
        layout.addRow("dt (s)", self.dt)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addRow(bb)
        self._on_kind_changed(self.kind.currentText())

    def _on_kind_changed(self, text: str):
        if text == "Transient":
            self._kind_help.setText(
                "<b>Transient</b> — time-domain simulation from 0→t_end with "
                "step dt. Required for any dynamic behaviour: capacitor/"
                "inductor charging, AC sources, battery SOC, PCS profiles, "
                "BMS state machines.")
            self.t_end.setEnabled(True)
            self.dt.setEnabled(True)
            self._cycle_btn.setEnabled(True)
        else:
            self._kind_help.setText(
                "<b>DC operating point</b> — solves the steady-state bias "
                "point only (t = 0; capacitors open, inductors shorted, AC "
                "sources at their DC value). Returns one snapshot, no "
                "waveforms. Useful as a sanity check before running a "
                "transient.")
            self.t_end.setEnabled(False)
            self.dt.setEnabled(False)
            self._cycle_btn.setEnabled(False)

    def _fill_from_cycle(self):
        total = _estimate_pcs_total_time(self._netlist)
        if total and total > 0:
            self.t_end.setText(f"{total:g}")

    def result_settings(self) -> dict:
        return {
            "kind": self.kind.currentText(),
            "t_end": float(self.t_end.text()),
            "dt": float(self.dt.text()),
        }
