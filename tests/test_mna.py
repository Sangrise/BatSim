import numpy as np
from batsim.engine.netlist import Netlist, Element
from batsim.engine.mna import solve_dc, solve_transient


def test_voltage_divider_dc():
    nl = Netlist()
    nl.add(Element("V", "V1", ["n1", "0"], {"V": 10.0}))
    nl.add(Element("R", "R1", ["n1", "n2"], {"R": 1000.0}))
    nl.add(Element("R", "R2", ["n2", "0"], {"R": 1000.0}))
    sys, x = solve_dc(nl)
    v = sys.node_voltages(x)
    assert abs(v["n1"] - 10.0) < 1e-9
    assert abs(v["n2"] - 5.0) < 1e-9


def test_rc_transient_charging():
    R, C = 1000.0, 1e-6  # tau = 1 ms
    nl = Netlist()
    nl.add(Element("V", "V1", ["n1", "0"], {"V": 5.0}))
    nl.add(Element("R", "R1", ["n1", "n2"], {"R": R}))
    nl.add(Element("C", "C1", ["n2", "0"], {"C": C}))
    res = solve_transient(nl, t_end=5e-3, dt=1e-5)
    v_final = res["V"]["n2"][-1]
    assert v_final > 4.9, f"Expected ~5V, got {v_final}"


def test_battery_rint_dc():
    from batsim.models.rint import RintModel
    nl = Netlist()
    nl.add(Element("BATTERY", "B1", ["n1", "0"],
                   {"capacity_Ah": 2.5, "soc0": 1.0, "R0": 0.05},
                   model=RintModel(R0=0.05, soc0=1.0)))
    nl.add(Element("R", "Rload", ["n1", "0"], {"R": 1.0}))
    sys, x = solve_dc(nl)
    v = sys.node_voltages(x)
    # OCV(1.0) ~ 3.0 + 1.2 - 0 + 0 = 4.2, with R0=0.05 + Rload=1.0 -> V_t close to 4.2*1/(1.05)
    assert 3.5 < v["n1"] < 4.3
