from batsim_core.models.rint import RintModel
from batsim_core.models.thevenin import TheveninModel
from batsim_core.models.n_rc import NRCModel


def test_rint_voltage_drop():
    m = RintModel(R0=0.1, soc0=1.0)
    v0 = m.terminal_voltage(0, None)
    m.update(I=10.0, dt=0.0, t=0.0)
    v1 = m.terminal_voltage(0, None)
    assert v1 == v0 - 1.0  # 10 A * 0.1 ohm


def test_thevenin_relaxation():
    m = TheveninModel(R0=0.0, R1=0.05, C1=1000.0)
    v_rest = m.terminal_voltage(0, None)
    # Apply 5A for 5 seconds
    for _ in range(500):
        m.update(I=5.0, dt=0.01, t=0.0)
    v_under_load = m.terminal_voltage(0, None)
    assert v_under_load < v_rest


def test_coulomb_counting():
    m = NRCModel(capacity_Ah=1.0, soc0=1.0)
    # 1 A for 3600 s -> 1 Ah, full discharge
    for _ in range(3600):
        m.update(I=1.0, dt=1.0, t=0.0)
    assert abs(m.soc) < 1e-6

