"""Grid-PCS-Bat-Bat (series) 10-cycle CPCV simulation, 3.0~4.2 V/cell.

Bat1 starts at ~3.0 V, Bat2 at ~3.3 V (NCM, 63 Ah).  Renders the result
as a PNG (pack/cell voltages, current, SOC) under
``out/grid_pcs_2bat.png``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from batsim.engine.netlist import from_graph
from batsim.engine.nonlinear import solve_transient
import batsim.plugins.builtin  # noqa: F401  (register built-in models)


# --- SOC initialisation helper ------------------------------------------
NCM = [(0.00, 3.00), (0.05, 3.40), (0.10, 3.50), (0.20, 3.58),
       (0.30, 3.63), (0.40, 3.68), (0.50, 3.74), (0.60, 3.81),
       (0.70, 3.89), (0.80, 3.99), (0.90, 4.10), (1.00, 4.20)]


def soc_for_voltage(v_target: float) -> float:
    socs = [s for s, _ in NCM]
    vs = [v for _, v in NCM]
    return float(np.interp(v_target, vs, socs))


CAPACITY_AH = 63.0
V_MAX_PACK = 8.4   # 4.2 V * 2 cells
V_MIN_PACK = 6.0   # 3.0 V * 2 cells
P_CHARGE = 500.0   # ~0.4C at 7 V pack
P_DISCHARGE = -500.0
I_TERM = 6.3       # 0.1C taper
MAX_PHASE_TIME = 5000.0  # safety upper-bound per phase (s)
N_CYCLES = 10


def build_graph() -> dict:
    bat_common = {
        "model": "Thevenin",
        "chemistry": "NCM",
        "capacity_Ah": CAPACITY_AH,
        "R0": 0.005,
        "R1": 0.003,
        "C1": 5000.0,
    }
    bat1 = dict(bat_common, soc0=soc_for_voltage(3.0))
    bat2 = dict(bat_common, soc0=soc_for_voltage(3.3))

    cycle_steps = [
        {"mode": "CPCV", "P": P_CHARGE,    "V_max": V_MAX_PACK,
         "I_term": I_TERM, "max_time": MAX_PHASE_TIME},
        {"mode": "CPCV", "P": P_DISCHARGE, "V_min": V_MIN_PACK,
         "I_term": I_TERM, "max_time": MAX_PHASE_TIME},
    ]

    components = [
        {"id": "GRID1", "kind": "BUS",
         "pins": [None, None],
         "params": {"mode": "Grid", "V": 400.0}},
        {"id": "PCS1", "kind": "PCS",
         "pins": [None, None, None, None],
         "params": {"mode": "CYCLE",
                    "cycle_steps": json.dumps(cycle_steps),
                    "cycle_repeat": N_CYCLES,
                    "eta": 0.98}},
        {"id": "B1", "kind": "BATTERY",
         "pins": [None, None], "params": bat1},
        {"id": "B2", "kind": "BATTERY",
         "pins": [None, None], "params": bat2},
    ]
    wires = [
        # AC: GRID line (pin0) -> PCS AC+ (pin0); GRID neutral & PCS AC-
        # are auto-grounded so we leave them implicit on node 0 via wire.
        {"a": "GRID1.0", "b": "PCS1.0"},
        {"a": "GRID1.1", "b": "PCS1.1"},
        # DC: PCS DC+ (pin2) -> B1+ (pin0); B1- (pin1) -> B2+ (pin0);
        # B2- (pin1) -> PCS DC- (pin3) [latter auto-grounded].
        {"a": "PCS1.2", "b": "B1.0"},
        {"a": "B1.1",   "b": "B2.0"},
        {"a": "B2.1",   "b": "PCS1.3"},
    ]
    return {"components": components, "wires": wires}


def main() -> int:
    graph = build_graph()
    nl = from_graph(graph)

    # Total simulation horizon: enough room for 10 full cycles, V/I
    # termination ends each phase early when limits are hit.
    t_end = N_CYCLES * 2 * MAX_PHASE_TIME
    dt = 5.0
    print(f"Solving transient: t_end={t_end:.0f}s  dt={dt}s "
          f"({int(t_end/dt)} steps) ...")
    res = solve_transient(nl, t_end=t_end, dt=dt)
    print("done.")

    t = res["t"]
    V = res["V"]
    I = res["I"]

    # Resolve node ids that correspond to physical points.
    pcs_dc_pos = nl.elements[[e.name for e in nl.elements].index("PCS1")].nodes[2]
    b1_pos = nl.elements[[e.name for e in nl.elements].index("B1")].nodes[0]
    b1_neg = nl.elements[[e.name for e in nl.elements].index("B1")].nodes[1]
    b2_pos = nl.elements[[e.name for e in nl.elements].index("B2")].nodes[0]
    b2_neg = nl.elements[[e.name for e in nl.elements].index("B2")].nodes[1]

    v_pack = V[pcs_dc_pos]
    v_b1 = V[b1_pos] - V.get(b1_neg, np.zeros_like(t))
    v_b2 = V[b2_pos] - V.get(b2_neg, np.zeros_like(t))

    # Battery branch current (VS convention: positive = into +pin from source,
    # so positive = battery is being charged).
    i_b1 = I["B1"]
    i_pcs = I["PCS1"]

    # Plot.
    out_dir = Path("out"); out_dir.mkdir(exist_ok=True)
    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    th = t / 3600.0

    # Median filter to suppress 1-step MNA glitches at controller transitions.
    from scipy.signal import medfilt as _medfilt
    def _smooth(arr, k=5):
        return _medfilt(arr, kernel_size=k)
    v_pack = _smooth(v_pack)
    v_b1 = _smooth(v_b1)
    v_b2 = _smooth(v_b2)
    i_b1 = _smooth(i_b1)

    ax = axes[0]
    ax.plot(th, v_pack, label="V(pack)", color="#1f77b4")
    ax.axhline(V_MAX_PACK, ls="--", color="r", lw=0.8, label=f"V_max={V_MAX_PACK} V")
    ax.axhline(V_MIN_PACK, ls="--", color="g", lw=0.8, label=f"V_min={V_MIN_PACK} V")
    ax.set_ylabel("Pack V")
    ax.set_ylim(3.0, 11.0)
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.set_title("Grid-PCS-Bat-Bat (NCM 63 Ah, series) — CPCV ×10 cycles")

    ax = axes[1]
    ax.plot(th, v_b1, label="V(B1)  soc0≈%.2f"
            % soc_for_voltage(3.0), color="#ff7f0e")
    ax.plot(th, v_b2, label="V(B2)  soc0≈%.2f"
            % soc_for_voltage(3.3), color="#2ca02c")
    ax.axhline(4.2, ls=":", color="r", lw=0.6)
    ax.axhline(3.0, ls=":", color="g", lw=0.6)
    ax.set_ylabel("Cell V")
    ax.set_ylim(1.5, 5.5)
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.3)

    ax = axes[2]
    ax.plot(th, i_b1, label="I(battery)  +chg / −dis", color="#9467bd")
    ax.axhline(0, color="k", lw=0.4)
    ax.set_ylabel("I [A]")
    ax.set_ylim(-300, 300)
    ax.set_xlabel("Time [h]")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    out_path = out_dir / "grid_pcs_2bat.png"
    fig.savefig(out_path, dpi=120)
    print(f"saved waveform → {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
