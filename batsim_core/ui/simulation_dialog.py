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


def _estimate_dt(netlist) -> tuple[float, str]:
    """Estimate a reasonable transient timestep from the schematic."""
    comps = list(getattr(netlist, "components", []) or [])
    for c in comps:
        if c.get("kind") != "GRID":
            continue
        try:
            freq = float(c.get("params", {}).get("freq", 0.0))
        except Exception:
            continue
        if freq > 0:
            dt = 1.0 / (20.0 * freq)
            return dt, f"GRID {freq:g} Hz 기준 20 samples/cycle"

    has_battery = any(
        c.get("kind") in ("BATTERY", "BATPACK", "BATRACK")
        for c in comps
    )
    if has_battery:
        return 1.0, "battery/slow DC 기본값"
    return 1e-3, "일반 회로 기본값"


def _parse_optional_positive_float(text: str, label: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    value = float(text)
    if value <= 0:
        raise ValueError(f"{label} must be greater than 0.")
    return value


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
        self._kind_help.setStyleSheet("color: #aeb8bf; font-size: 11px;")

        self.t_end = QLineEdit("")
        self.t_end.setPlaceholderText("Auto")
        self.dt = QLineEdit("")
        self.dt.setPlaceholderText("Auto")

        # "Use PCS cycle length" helper button
        t_end_row = QWidget()
        h = QHBoxLayout(t_end_row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.t_end, 1)
        self._cycle_btn = QPushButton("Auto from PCS cycle")
        self._cycle_btn.setToolTip(
            "Compute t_end from PCS cycle steps.\n"
            "PCS cycles describe WHAT to do; t_end limits HOW LONG\n"
            "to simulate. They are independent — if t_end < cycle\n"
            "duration, the simulation stops early; if larger, the PCS\n"
            "stays in DONE state after the cycle finishes.")
        self._cycle_btn.clicked.connect(self._fill_from_cycle)
        h.addWidget(self._cycle_btn)

        layout.addRow("Type", self.kind)
        layout.addRow("", self._kind_help)
        layout.addRow("End time (s)", t_end_row)
        layout.addRow("Time step (s)", self.dt)
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
                "<b>Transient</b> — normal time-domain run. Produces "
                "waveforms and updates dynamic state such as capacitors, "
                "inductors, AC sources, battery SOC, PCS cycles, and BMS "
                "logic. Leave End time/Time step blank for Auto.")
            self.t_end.setEnabled(True)
            self.dt.setEnabled(True)
            self._cycle_btn.setEnabled(True)
        else:
            self._kind_help.setText(
                "<b>DC operating point</b> — one static t=0 sanity check. "
                "Capacitors are open, inductors are shorted, and AC sources "
                "use their DC value. It returns voltages only, no waveforms.")
            self.t_end.setEnabled(False)
            self.dt.setEnabled(False)
            self._cycle_btn.setEnabled(False)

    def _fill_from_cycle(self):
        total = _estimate_pcs_total_time(self._netlist)
        if total and total > 0:
            self.t_end.setText(f"{total:g}")

    def result_settings(self) -> dict:
        if self.kind.currentText() == "DC operating point":
            return {"kind": self.kind.currentText(), "t_end": None, "dt": None}

        t_end = _parse_optional_positive_float(self.t_end.text(), "End time")
        dt = _parse_optional_positive_float(self.dt.text(), "Time step")
        t_reason = "manual"
        dt_reason = "manual"
        if t_end is None:
            total = _estimate_pcs_total_time(self._netlist)
            if total and total > 0:
                t_end = total
                t_reason = "auto from PCS cycle"
            else:
                t_end = 60.0
                t_reason = "default"
        if dt is None:
            dt, dt_reason = _estimate_dt(self._netlist)
        return {
            "kind": self.kind.currentText(),
            "t_end": t_end,
            "dt": dt,
            "t_end_reason": t_reason,
            "dt_reason": dt_reason,
        }
