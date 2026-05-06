"""Simulation configuration dialog."""
from __future__ import annotations

import json

from PyQt6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QDialogButtonBox,
                             QComboBox, QLabel, QPushButton, QHBoxLayout,
                             QWidget)


def _step_duration_estimate(s: dict, cap_Ah: float | None,
                            n_series: int = 1) -> float:
    """Estimate one CYCLE step's actual runtime (seconds).

    Heuristic — uses energy / power for CC & CP steps so the
    "Auto from PCS cycle" button doesn't grossly over-estimate when
    ``max_time`` was set as a safety cap.  Falls back to ``max_time``
    or ``time`` if the heuristic isn't applicable.
    """
    sm = str(s.get("mode", "REST")).upper()
    max_time = None
    try:
        if "max_time" in s:
            max_time = float(s["max_time"])
        elif "time" in s:
            max_time = float(s["time"])
    except Exception:
        max_time = None

    # Effective pack-level voltage thresholds (per-cell × N if needed).
    def _eff(key, key_cell):
        if key_cell in s:
            try:
                return float(s[key_cell]) * max(int(n_series), 1)
            except Exception:
                return None
        if key in s:
            try:
                return float(s[key])
            except Exception:
                return None
        return None
    V_max = _eff("V_max", "V_max_cell")
    V_min = _eff("V_min", "V_min_cell")
    # Nominal pack voltage for energy estimate.
    if V_max and V_min:
        V_nom = 0.5 * (V_max + V_min)
    elif V_max:
        V_nom = V_max
    elif V_min:
        V_nom = V_min
    else:
        # 4.0 V/cell default if user didn't specify any V threshold.
        V_nom = 4.0 * max(int(n_series), 1)

    est = None
    if sm == "REST":
        try:
            est = float(s.get("time", s.get("max_time", 0)) or 0)
        except Exception:
            est = 0.0
    elif sm == "CC":
        try:
            I = abs(float(s.get("I", 0.0)))
        except Exception:
            I = 0.0
        if cap_Ah and I > 0:
            est = 3600.0 * cap_Ah / I  # full SoC swing
    elif sm == "CP":
        try:
            P = abs(float(s.get("P", 0.0)))
        except Exception:
            P = 0.0
        if cap_Ah and P > 0 and V_nom > 0:
            est = 3600.0 * cap_Ah * V_nom / P
    elif sm in ("CV", "CCCV", "CPCV"):
        # CV taper hard to estimate analytically — use max_time if given,
        # else assume 1 hour.
        est = max_time if max_time is not None else 3600.0

    if est is None:
        return max_time if max_time is not None else 0.0
    if max_time is not None:
        return min(est, max_time)
    return est


def _estimate_pcs_total_time(netlist) -> float | None:
    """Estimate total simulation time covering all PCS cycle modes."""
    if netlist is None:
        return None
    comps = list(getattr(netlist, "components", []) or [])
    cap_Ah = None
    for c in comps:
        if c.get("kind") in ("BATTERY", "BATPACK", "BATRACK"):
            try:
                cap_Ah = float(c.get("params", {}).get("capacity_Ah", 0.0))
                if c.get("kind") in ("BATPACK", "BATRACK"):
                    cap_Ah *= int(c.get("params", {}).get("n_parallel", 1) or 1)
                if cap_Ah > 0:
                    break
            except Exception:
                pass

    best = 0.0
    found = False
    for c in comps:
        if c.get("kind") != "PCS":
            continue
        params = c.get("params", {})
        mode = params.get("mode", "")
        n_series = int(params.get("n_series", 1) or 1)

        if mode == "CYCLE_SIMPLE":
            try:
                I_chg = abs(float(params.get("cyc_I_chg", 0.0)))
                I_dis = abs(float(params.get("cyc_I_dis", 0.0)))
                t_rest = float(params.get("cyc_t_rest", 0.0))
                cycles = int(params.get("cyc_count", 1) or 1)
            except Exception:
                continue
            t_chg = (3600.0 * cap_Ah / I_chg) if (cap_Ah and I_chg > 0) else 3600.0
            t_dis = (3600.0 * cap_Ah / I_dis) if (cap_Ah and I_dis > 0) else 3600.0
            per = t_chg + t_dis + 2 * t_rest
            total = per * max(cycles, 1)
            if total > 0:
                found = True; best = max(best, total)
            continue

        if mode != "CYCLE":
            continue
        raw = params.get("cycle_steps", "[]")
        try:
            steps = raw if isinstance(raw, list) else json.loads(raw)
        except Exception:
            continue
        per_cycle = 0.0
        for s in steps:
            if not isinstance(s, dict):
                continue
            per_cycle += _step_duration_estimate(s, cap_Ah, n_series)
        repeat = int(params.get("cycle_repeat", 1) or 1)
        if repeat <= 0:
            continue
        total = per_cycle * repeat
        if total > 0:
            found = True; best = max(best, total)
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
