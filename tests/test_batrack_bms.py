"""BATRACK (series of BATPACKs) + BMS (control-domain) component tests."""
from __future__ import annotations

from batsim.engine.netlist import from_graph
from batsim.engine.nonlinear import solve_transient
from batsim.bms.cell_balancer import PassiveBalancerV1
from batsim.plugins import discover

discover()


def _rack_params(**ov):
    p = {
        "model": "Thevenin",
        "n_packs_series": 3,
        "n_series": 2,
        "n_parallel": 1,
        "capacity_Ah": 1.0,
        "soc0": 0.6,
        "soc_init_spread": 0.0,
        "R0": 0.0,
        "R1": 0.001,
        "C1": 1000.0,
        "balancer": "None",
    }
    p.update(ov)
    return p


def _rack_only_graph(**ov):
    return {
        "components": [
            {"id": "BR1", "kind": "BATRACK", "pins": [None, None],
             "params": _rack_params(**ov)},
            {"id": "R1", "kind": "R", "pins": ["BR1.0", "BR1.1"],
             "params": {"R": 1e6}},  # negligible load
        ],
        "wires": [],
    }


def test_batrack_voltage_is_sum_of_packs():
    g = _rack_only_graph(n_packs_series=3, n_series=2, soc0=1.0, R0=0.0)
    nl = from_graph(g)
    br = next(e for e in nl.elements if e.kind == "BATRACK")
    pack_v = br.model.packs[0].terminal_voltage(0, None)
    assert abs(br.model.terminal_voltage(0.0, None) - 3 * pack_v) < 1e-9
    # Also verify rack composition: 3 packs each with 2 series cells.
    assert len(br.model.packs) == 3
    assert all(len(p.cells) == 2 for p in br.model.packs)


def test_batrack_capacity_equals_one_pack_capacity():
    # Series stacking adds voltage, not Ah.
    g = _rack_only_graph(n_packs_series=4, n_parallel=2, capacity_Ah=2.0)
    nl = from_graph(g)
    br = next(e for e in nl.elements if e.kind == "BATRACK")
    assert br.model.capacity_Ah == 4.0  # 2 Ah/cell × 2 strings, ×1 pack


def test_batrack_runs_transient_drives_inner_state():
    g = _rack_only_graph()
    g["components"][1]["params"]["R"] = 100.0  # actually load it
    nl = from_graph(g)
    br = next(e for e in nl.elements if e.kind == "BATRACK")
    soc0 = br.model.soc
    solve_transient(nl, t_end=10.0, dt=0.1)
    assert br.model.soc != soc0


# ---------------------------------------------------------------------------
# BMS component
# ---------------------------------------------------------------------------

def _two_rack_graph(bms_components):
    return {
        "components": [
            {"id": "BR1", "kind": "BATRACK", "pins": [None, None],
             "params": _rack_params(balancer="None", soc_init_spread=0.10,
                                    soc0=0.6)},
            {"id": "BR2", "kind": "BATRACK", "pins": [None, None],
             "params": _rack_params(balancer="None", soc_init_spread=0.10,
                                    soc0=0.6)},
            {"id": "R1", "kind": "R", "pins": ["BR1.0", "BR1.1"],
             "params": {"R": 1e6}},
            {"id": "R2", "kind": "R", "pins": ["BR2.0", "BR2.1"],
             "params": {"R": 1e6}},
            *bms_components,
        ],
        "wires": [],
    }


def test_bms_overrides_balancer_on_listed_targets_only():
    bms = [
        {"id": "BMS1", "kind": "BMS", "pins": [],
         "params": {
             "targets": "BR1",     # BR2 is left untouched
             "balancer": "PassiveV1",
             "balancer_soc_enable": 0.0,
             "balancer_dev_min":    0.005,
             "balancer_dev_max":    1.0,
             "balancer_soc_drop":   0.001,
             "balancer_I_bal":      1.0,
             "balancer_pack_pause": 0.0,
             "balancer_pack_resume":0.0,
         }},
    ]
    nl = from_graph(_two_rack_graph(bms))
    br1 = next(e for e in nl.elements if e.name == "BR1")
    br2 = next(e for e in nl.elements if e.name == "BR2")
    # BR1: every pack got a PassiveV1 balancer pushed by the BMS.
    assert all(isinstance(p.balancer, PassiveBalancerV1) for p in br1.model.packs)
    assert all(p.balancer.dev_min == 0.005 for p in br1.model.packs)
    # BR2: no BMS targeted it → keeps its original "None" balancer.
    assert all(p.balancer is None for p in br2.model.packs)


def test_one_bms_can_own_multiple_racks_with_same_logic():
    bms = [
        {"id": "BMS1", "kind": "BMS", "pins": [],
         "params": {
             "targets": "BR1, BR2",
             "balancer": "PassiveV1",
             "balancer_soc_enable": 0.0,
             "balancer_dev_min":    0.04,
             "balancer_dev_max":    1.0,
             "balancer_soc_drop":   0.001,
             "balancer_I_bal":      2.5,
             "balancer_pack_pause": 0.0,
             "balancer_pack_resume":0.0,
         }},
    ]
    nl = from_graph(_two_rack_graph(bms))
    br1 = next(e for e in nl.elements if e.name == "BR1")
    br2 = next(e for e in nl.elements if e.name == "BR2")
    for br in (br1, br2):
        for p in br.model.packs:
            assert isinstance(p.balancer, PassiveBalancerV1)
            assert p.balancer.dev_min == 0.04
            assert p.balancer.I_bal == 2.5


def test_two_bmses_apply_independent_logic_to_disjoint_racks():
    bms = [
        {"id": "BMS_A", "kind": "BMS", "pins": [],
         "params": {"targets": "BR1", "balancer": "PassiveV1",
                    "balancer_soc_enable": 0.0, "balancer_dev_min": 0.01,
                    "balancer_dev_max": 1.0, "balancer_soc_drop": 0.001,
                    "balancer_I_bal": 0.5, "balancer_pack_pause": 0.0,
                    "balancer_pack_resume": 0.0}},
        {"id": "BMS_B", "kind": "BMS", "pins": [],
         "params": {"targets": "BR2", "balancer": "PassiveV1",
                    "balancer_soc_enable": 0.0, "balancer_dev_min": 0.08,
                    "balancer_dev_max": 1.0, "balancer_soc_drop": 0.001,
                    "balancer_I_bal": 3.0, "balancer_pack_pause": 0.0,
                    "balancer_pack_resume": 0.0}},
    ]
    nl = from_graph(_two_rack_graph(bms))
    br1 = next(e for e in nl.elements if e.name == "BR1")
    br2 = next(e for e in nl.elements if e.name == "BR2")
    assert br1.model.packs[0].balancer.dev_min == 0.01
    assert br1.model.packs[0].balancer.I_bal == 0.5
    assert br2.model.packs[0].balancer.dev_min == 0.08
    assert br2.model.packs[0].balancer.I_bal == 3.0


def test_bms_inherit_does_not_overwrite_pack_balancer():
    g = _two_rack_graph([
        {"id": "BMS1", "kind": "BMS", "pins": [],
         "params": {"targets": "BR1,BR2", "balancer": "Inherit"}},
    ])
    # Configure BR1 with PassiveV1 baked in.
    g["components"][0]["params"]["balancer"] = "PassiveV1"
    g["components"][0]["params"]["balancer_dev_min"] = 0.123
    nl = from_graph(g)
    br1 = next(e for e in nl.elements if e.name == "BR1")
    assert isinstance(br1.model.packs[0].balancer, PassiveBalancerV1)
    assert br1.model.packs[0].balancer.dev_min == 0.123  # kept


def test_bms_is_not_added_to_netlist_as_an_element():
    g = _two_rack_graph([
        {"id": "BMS1", "kind": "BMS", "pins": [],
         "params": {"targets": "BR1", "balancer": "Inherit"}},
    ])
    nl = from_graph(g)
    assert all(e.kind != "BMS" for e in nl.elements)


def test_bms_controlled_balancing_reduces_imbalance_in_transient():
    g = {
        "components": [
            {"id": "BR1", "kind": "BATRACK", "pins": [None, None],
             "params": _rack_params(balancer="None", soc_init_spread=0.10,
                                    soc0=0.6)},
            {"id": "R1", "kind": "R", "pins": ["BR1.0", "BR1.1"],
             "params": {"R": 1e6}},
            {"id": "BMS1", "kind": "BMS", "pins": [],
             "params": {
                 "targets": "BR1",
                 "balancer": "PassiveV1",
                 "balancer_soc_enable": 0.0,
                 "balancer_dev_min":    0.005,
                 "balancer_dev_max":    1.0,
                 "balancer_soc_drop":   0.001,
                 "balancer_I_bal":      1.0,
                 "balancer_pack_pause": 0.0,
                 "balancer_pack_resume":0.0,
                 "balancer_rest_min":   0.0,
             }},
        ],
        "wires": [],
    }
    nl = from_graph(g)
    br1 = next(e for e in nl.elements if e.name == "BR1")
    cells0 = [c.soc for p in br1.model.packs for row in p.cells for c in row]
    spread0 = max(cells0) - min(cells0)
    solve_transient(nl, t_end=200.0, dt=1.0)
    cells1 = [c.soc for p in br1.model.packs for row in p.cells for c in row]
    spread1 = max(cells1) - min(cells1)
    assert spread1 < spread0
def test_rack_exposes_per_pack_voltage_and_per_cell_v_t_and_rack_current():
    g = {
        "components": [
            {"id": "BR1", "kind": "BATRACK", "pins": [None, None],
             "params": _rack_params(n_packs_series=3, n_series=2,
                                    n_parallel=2, soc_init_spread=0.05,
                                    balancer="None")},
            {"id": "R1", "kind": "R", "pins": ["BR1.0", "BR1.1"],
             "params": {"R": 1e6}},
        ],
        "wires": [],
    }
    nl = from_graph(g)
    br = next(e for e in nl.elements if e.name == "BR1")
    solve_transient(nl, t_end=5.0, dt=1.0)
    pv = br.model.pack_voltages()
    assert len(pv) == 3
    assert all(2.0 < v < 50.0 for v in pv)
    cv = br.model.cell_voltages()
    assert len(cv) == 3 and len(cv[0]) == 2 and len(cv[0][0]) == 2
    ct = br.model.cell_temperatures()
    assert all(t == 25.0 for pack in ct for row in pack for t in row)
    assert br.model.I_rack == br.model._I


def test_rack_set_thermal_model_propagates_to_every_pack_and_cell():
    from batsim.models.rack import BatteryRackModel
    from batsim.models.pack import BatteryPackModel

    rack = BatteryRackModel(
        n_packs_series=2,
        pack_factory=lambda: BatteryPackModel(n_series=2, n_parallel=1,
                                              balancer="None"),
    )

    class _Stub:
        def update(self, I_cell, V_cell, dt, t):
            return 42.0

    rack.set_thermal_model(_Stub)
    flat = [c for p in rack.packs for row in p.cells for c in row]
    assert all(c.thermal_model is not None for c in flat)
    rack.update(I=1.0, dt=1.0, t=0.0)
    assert all(c.T_cell == 42.0 for c in flat)
