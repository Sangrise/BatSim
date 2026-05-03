import math
import numpy as np
from batsim.engine.netlist import Netlist, Element
from batsim.engine.nonlinear import solve_dc, solve_transient


def test_diode_forward_bias_dc():
    nl = Netlist()
    nl.add(Element("V", "V1", ["a", "0"], {"V": 1.0}))
    nl.add(Element("R", "R1", ["a", "b"], {"R": 1000.0}))
    nl.add(Element("DIODE", "D1", ["b", "0"], {"Is": 1e-12, "n": 1.0, "Vt": 0.02585}))
    sys, x = solve_dc(nl)
    v = sys.node_voltages(x)
    # Diode clamp ~0.6-0.7 V
    assert 0.4 < v["b"] < 0.8


def test_diode_reverse_bias_blocks():
    nl = Netlist()
    nl.add(Element("V", "V1", ["a", "0"], {"V": -1.0}))
    nl.add(Element("R", "R1", ["a", "b"], {"R": 1000.0}))
    nl.add(Element("DIODE", "D1", ["b", "0"], {"Is": 1e-12, "n": 1.0, "Vt": 0.02585}))
    sys, x = solve_dc(nl)
    v = sys.node_voltages(x)
    # Reverse-biased diode -> tiny current -> node b ~ -1V
    assert v["b"] < -0.5


def test_mosfet_saturation():
    # NMOS with Vgs=2, Vth=1 => saturation Id = 0.5 * Kp * (Vgs-Vth)^2
    Kp = 1e-3
    nl = Netlist()
    nl.add(Element("V", "Vgs", ["g", "0"], {"V": 2.0}))
    nl.add(Element("V", "Vds", ["d", "0"], {"V": 5.0}))
    nl.add(Element("MOSFET", "M1", ["d", "g", "0"], {"Kp": Kp, "Vth": 1.0, "lambda": 0.0}))
    sys, x = solve_dc(nl)
    Id = sys.vs_current(x, "Vds")  # current through Vds
    # Conventional: current flowing into +node of Vds; should be negative (sourcing)
    expected = 0.5 * Kp * 1.0**2
    assert abs(abs(Id) - expected) < expected * 0.2


def test_spm_discharges_voltage():
    from batsim.models.spm import SPMModel
    m = SPMModel(capacity_Ah=2.5, soc0=1.0, R0=0.02)
    v0 = m.terminal_voltage(0, None)
    for _ in range(3600):
        m.update(I=2.5, dt=1.0, t=0.0)  # 1C for 1h -> empty
    v1 = m.terminal_voltage(0, None)
    assert v1 < v0
    assert m.soc < 0.05


def test_ekf_converges():
    from batsim.bms.ekf_soc import EKFSocEstimator
    from batsim.models.thevenin import TheveninModel
    truth = TheveninModel(capacity_Ah=2.5, soc0=0.7, R0=0.03, R1=0.02, C1=2000.0)
    ekf = EKFSocEstimator(capacity_Ah=2.5, soc0=1.0, R0=0.03, R1=0.02, C1=2000.0)
    dt = 1.0
    I = 1.0
    for _ in range(600):
        truth.update(I=I, dt=dt, t=0.0)
        V = truth.terminal_voltage(0, None)
        ekf.step(I=I, V_meas=V, dt=dt)
    assert abs(ekf.soc - truth.soc) < 0.05


def test_cccv_controller():
    from batsim.bms.controller import CCCVController
    c = CCCVController(I_charge=1.0, V_cv=4.20, mode="charge")
    assert c.command(V_t=3.5) == -1.0  # CC region
    assert abs(c.command(V_t=4.20)) < 1e-9 or c.command(V_t=4.20) == 0.0  # at CV target
    c.mode = "discharge"
    assert c.command(V_t=3.7) == 1.0
