from batsim.bms.protection import Protector, ProtectionLimits
from batsim.bms.balancer import PassiveBalancer
from batsim.bms.soc_estimator import CoulombCounter


def test_protection_overvoltage():
    p = Protector(ProtectionLimits(V_over=4.2))
    assert p.check(V=4.0, I=1.0) is True
    assert p.check(V=4.3, I=1.0) is False
    assert p.fault == "OV"


def test_balancer_picks_high_cells():
    b = PassiveBalancer(threshold_V=0.005)
    mask = b.select([3.70, 3.72, 3.71])
    assert mask == [False, True, True]


def test_coulomb_counter():
    cc = CoulombCounter(capacity_Ah=2.0, soc0=1.0)
    cc.update(I=2.0, dt=3600.0)  # 1 full discharge
    assert abs(cc.soc) < 1e-9
