"""Tests for the new charge/discharge pattern components and undo manager.

UI-side undo behaviour is exercised manually via the running app (Ctrl+Z/
Ctrl+Y) — the engine pieces are covered here in isolation."""
from __future__ import annotations

import os
import sys
import tempfile

import pytest


# ---------------------------------------------------------------- engine
def test_iconst_dc():
    from batsim_core.engine.netlist import Netlist, Element
    from batsim_core.engine.nonlinear import solve_dc
    nl = Netlist()
    nl.add(Element("ICONST", "I1", ["n1", "0"], {"I": 1.0}))
    nl.add(Element("R", "R1", ["n1", "0"], {"R": 100.0}))
    sys_, x = solve_dc(nl)
    v = sys_.node_voltages(x)
    # ICONST sinks current from n1 -> 0, so v(n1) = -100 V
    assert abs(v["n1"] + 100.0) < 1e-6


def test_pconst_dc():
    """A 5V source feeding a 10W load draws 2A (|V1 current| == 2)."""
    from batsim_core.engine.netlist import Netlist, Element
    from batsim_core.engine.nonlinear import solve_dc
    nl = Netlist()
    nl.add(Element("V", "V1", ["n1", "0"], {"V": 5.0}))
    nl.add(Element("PCONST", "P1", ["n1", "0"], {"P": 10.0}))
    sys_, x = solve_dc(nl)
    v = sys_.node_voltages(x)
    assert abs(v["n1"] - 5.0) < 1e-6
    I = sys_.vs_current(x, "V1")
    assert abs(abs(I) - 2.0) < 1e-3


def test_ipattern_csv():
    from batsim_core.engine.sources import make_csv_waveform
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                     newline="") as f:
        f.write("# time, current\n")
        f.write("0,0\n0.5,1\n1.0,0\n")
        path = f.name
    try:
        wf = make_csv_waveform(path, scale=2.0, repeat=True)
        assert abs(wf(0.0)) < 1e-9
        assert abs(wf(0.5) - 2.0) < 1e-9   # 1.0 * scale
        assert abs(wf(1.0)) < 1e-9
        assert abs(wf(1.5) - 2.0) < 1e-9   # repeat: 1.5 mod 1 = 0.5
    finally:
        os.unlink(path)


def test_ipattern_missing_file_returns_default():
    from batsim_core.engine.sources import make_csv_waveform
    wf = make_csv_waveform("/no/such/file.csv", default=0.42)
    assert abs(wf(0.0) - 0.42) < 1e-9
    assert abs(wf(99.0) - 0.42) < 1e-9


def test_ipattern_in_transient():
    """End-to-end transient with an IPATTERN sourcing into a resistor."""
    from batsim_core.engine.netlist import Netlist, Element
    from batsim_core.engine.nonlinear import solve_transient
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                     newline="") as f:
        f.write("0,0\n1,1\n2,1\n3,0\n")
        path = f.name
    try:
        nl = Netlist()
        nl.add(Element("IPATTERN", "I1", ["n1", "0"],
                       {"csv": path, "scale": 1.0, "repeat": False, "I": 0.0}))
        nl.add(Element("R", "R1", ["n1", "0"], {"R": 1.0}))
        result = solve_transient(nl, t_end=3.0, dt=0.5)
        Vs = result["V"]["n1"]
        # At t=2, current is 1A through 1Ω (sink), so v(n1) = -1
        idx_t2 = int(2.0 / 0.5)
        assert abs(Vs[idx_t2] + 1.0) < 1e-3
    finally:
        os.unlink(path)


def test_inspector_param_change_records_undo():
    pytest.importorskip("PyQt6")
    from PyQt6.QtCore import QPointF
    from PyQt6.QtWidgets import QApplication
    from batsim_core.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    try:
        r = win.scene.add_component("R", QPointF(0, 0))
        win._reset_undo_history()
        win.inspector.set_component(r)

        win.inspector._update_param("R", "2200")

        assert r.params["R"] == 2200.0
        assert len(win._undo_stack) == 1
        win.undo()
        r2 = next(c for c in win.scene._components if c.kind == "R")
        assert r2.params["R"] == 1000.0
    finally:
        win.close()

