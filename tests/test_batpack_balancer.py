"""Tests for the BATPACK series/parallel battery component and the
PassiveV1 cell-balancing algorithm."""
from __future__ import annotations

from batsim.engine.netlist import from_graph
from batsim.engine.nonlinear import solve_transient
from batsim.bms.cell_balancer import (PassiveBalancerV1, list_balancers,
                                      make_balancer)
from batsim.models.pack import BatteryPackModel
from batsim.plugins import discover

discover()


def _pack_graph(**pack_overrides):
    pack_params = {
        "model": "Thevenin",
        "n_series": 4,
        "n_parallel": 2,
        "capacity_Ah": 1.0,
        "soc0": 0.5,
        "soc_init_spread": 0.0,
        "R0": 0.05,
        "R1": 0.001,
        "C1": 1000.0,
        "balancer": "None",
    }
    pack_params.update(pack_overrides)
    return {
        "components": [
            {"id": "BP1", "kind": "BATPACK", "pins": [None, None],
             "params": pack_params},
            {"id": "R1", "kind": "R", "pins": ["BP1.0", "BP1.1"],
             "params": {"R": 100.0}},
        ],
        "wires": [],
    }


def test_batpack_terminal_voltage_sums_series_rows():
    g = _pack_graph(n_series=3, n_parallel=2, soc0=1.0, R0=0.0)
    nl = from_graph(g)
    bp = next(e for e in nl.elements if e.kind == "BATPACK")
    v_cell = bp.model.cells[0][0].terminal_voltage(0, None)
    assert abs(bp.model.terminal_voltage(0.0, None) - 3 * v_cell) < 1e-9


def test_batpack_capacity_scales_with_parallel_strings():
    g = _pack_graph(capacity_Ah=2.0, n_parallel=3)
    nl = from_graph(g)
    bp = next(e for e in nl.elements if e.kind == "BATPACK")
    assert bp.model.capacity_Ah == 6.0


def test_batpack_runs_transient_and_drains_soc():
    g = _pack_graph(soc0=0.9)
    nl = from_graph(g)
    bp = next(e for e in nl.elements if e.kind == "BATPACK")
    soc0 = bp.model.soc
    solve_transient(nl, t_end=10.0, dt=0.1)
    # Pack participated in the transient (SOC moved from initial value).
    # Sign of the change tracks the existing BATTERY convention in the
    # solver; we only verify the model is being driven.
    assert bp.model.soc != soc0


def test_passive_v1_pause_resume_hysteresis():
    bal = PassiveBalancerV1(soc_enable=0.0, dev_min=0.0,
                            soc_drop=1.0, I_bal=1.0,
                            pack_pause=0.05, pack_resume=0.08,
                            rest_min=0.0)

    class _Cell:
        def __init__(self, soc):
            self.soc = soc
            self.capacity_Ah = 1.0

    # avg high → balancing active
    cells = [_Cell(0.5), _Cell(0.4)]
    out = bal.bleed_currents(cells, dt=1.0, t=0.0)
    assert any(c > 0 for c in out)

    # avg drops to 0.04 (below pause threshold) → all bleeds suspended
    cells = [_Cell(0.04), _Cell(0.04)]
    out = bal.bleed_currents(cells, dt=1.0, t=1.0)
    assert all(c == 0 for c in out)
    assert bal._paused

    # still below resume threshold (0.06 < 0.08) → still paused
    cells = [_Cell(0.06), _Cell(0.06)]
    out = bal.bleed_currents(cells, dt=1.0, t=2.0)
    assert all(c == 0 for c in out)
    assert bal._paused

    # avg above resume threshold (0.09 ≥ 0.08) → balancing resumes
    cells = [_Cell(0.12), _Cell(0.06)]
    out = bal.bleed_currents(cells, dt=1.0, t=3.0)
    assert not bal._paused
    assert out[0] > 0  # high-SOC cell bleeds


def test_passive_v1_only_targets_high_deviation_cells():
    bal = PassiveBalancerV1(soc_enable=0.46, dev_min=0.02,
                            soc_drop=10.0, I_bal=1.0,
                            pack_pause=0.0, pack_resume=0.0,
                            rest_min=0.0)

    class _Cell:
        def __init__(self, soc):
            self.soc = soc
            self.capacity_Ah = 1.0

    # Cell 0 is only 0.005 above min → below dev_min, should NOT bleed.
    # Cell 1 is the min. Cell 2 is 0.05 above min → eligible.
    cells = [_Cell(0.505), _Cell(0.50), _Cell(0.55)]
    out = bal.bleed_currents(cells, dt=1.0, t=0.0)
    assert out[0] == 0.0
    assert out[1] == 0.0
    assert out[2] == 1.0


def test_passive_v1_slot_runs_until_target_drop_reached():
    # soc_drop=0.001, I_bal=1A, capacity=1Ah → slot length = 0.001*3600 = 3.6s.
    bal = PassiveBalancerV1(soc_enable=0.0, dev_min=0.05,
                            soc_drop=0.001, I_bal=1.0,
                            pack_pause=0.0, pack_resume=0.0,
                            rest_min=0.0)

    class _Cell:
        def __init__(self, soc):
            self.soc = soc
            self.capacity_Ah = 1.0

    # Two-cell string: cell 0 starts 0.10 above min → eligible.
    cells = [_Cell(0.60), _Cell(0.50)]
    bal.bleed_currents(cells, dt=1.0, t=0.0)  # starts slot on cell 0

    # Now externally drop cell 0's SOC below cell 1 (mimicking continued
    # bleed + pack discharge).  The slot must keep running until its
    # timer expires regardless of the new ordering.
    cells[0].soc = 0.30
    for _ in range(3):
        out = bal.bleed_currents(cells, dt=1.0, t=0.0)
        assert out[0] == 1.0
    # After total 4s elapsed (>3.6s slot length), bleed expires.  Cell 0
    # is now the min and below dev_min so no new slot starts.
    out = bal.bleed_currents(cells, dt=1.0, t=0.0)
    assert out[0] == 0.0


def test_balancer_registry_lists_passive_v1_and_none():
    names = list_balancers()
    assert "None" in names
    assert "PassiveV1" in names
    assert make_balancer("None") is None
    assert isinstance(make_balancer("PassiveV1"), PassiveBalancerV1)


def test_passive_v1_registered_as_bms_block():
    # Cell balancing is a BMS function; algorithms must show up in the
    # global BMS registry (used by `batsim list-bms`) under a "balancer:"
    # prefix.
    import batsim.bms  # noqa: F401  — triggers registration
    from batsim.plugins.registry import BMS_BLOCKS
    assert "balancer:PassiveV1" in BMS_BLOCKS
    assert BMS_BLOCKS["balancer:PassiveV1"] is PassiveBalancerV1


def test_passive_v1_dev_max_excludes_outlier_cells():
    # dev_max = 0.10 → cells more than 10% above min are skipped.
    bal = PassiveBalancerV1(soc_enable=0.0, dev_min=0.02, dev_max=0.10,
                            soc_drop=10.0, I_bal=1.0,
                            pack_pause=0.0, pack_resume=0.0,
                            rest_min=0.0)

    class _Cell:
        def __init__(self, soc):
            self.soc = soc
            self.capacity_Ah = 1.0

    # min=0.50, cell0 dev=0.05 (eligible), cell2 dev=0.20 (excluded).
    cells = [_Cell(0.55), _Cell(0.50), _Cell(0.70)]
    out = bal.bleed_currents(cells, dt=1.0, t=0.0)
    assert out[0] == 1.0   # within (dev_min, dev_max) → bleed
    assert out[1] == 0.0   # is the min
    assert out[2] == 0.0   # outlier, excluded by dev_max


def test_passive_v1_dev_max_default_excludes_nothing():
    # Default dev_max=1.0 ⇒ practically no exclusion.
    bal = PassiveBalancerV1(soc_enable=0.0, dev_min=0.02,
                            soc_drop=10.0, I_bal=1.0,
                            pack_pause=0.0, pack_resume=0.0,
                            rest_min=0.0)
    assert bal.dev_max == 1.0

    class _Cell:
        def __init__(self, soc):
            self.soc = soc
            self.capacity_Ah = 1.0

    cells = [_Cell(0.95), _Cell(0.05)]
    out = bal.bleed_currents(cells, dt=1.0, t=0.0)
    assert out[0] == 1.0  # huge gap but still under default dev_max


def test_batpack_with_passive_v1_reduces_imbalance_over_time():
    g = _pack_graph(n_series=4, n_parallel=1,
                    capacity_Ah=1.0, soc0=0.6,
                    soc_init_spread=0.10,
                    R0=0.0, R1=0.001, C1=1000.0,
                    balancer="PassiveV1",
                    balancer_soc_enable=0.0,
                    balancer_dev_min=0.005,
                    balancer_soc_drop=0.001,
                    balancer_I_bal=1.0,
                    balancer_pack_pause=0.0,
                    balancer_pack_resume=0.0,
                    balancer_rest_min=0.0)
    # Replace load with a high resistor so the pack barely discharges;
    # imbalance reduction should come from the bleed, not from the load.
    g["components"][1]["params"]["R"] = 1e6
    nl = from_graph(g)
    bp = next(e for e in nl.elements if e.kind == "BATPACK")
    socs0 = [c.soc for row in bp.model.cells for c in row]
    spread0 = max(socs0) - min(socs0)
    solve_transient(nl, t_end=200.0, dt=1.0)
    socs1 = [c.soc for row in bp.model.cells for c in row]
    spread1 = max(socs1) - min(socs1)
    assert spread1 < spread0
def test_pack_exposes_per_cell_voltage_and_temperature_and_pack_current():
    nl = from_graph(_pack_graph(soc_init_spread=0.10))
    bp = next(e for e in nl.elements if e.name == "BP1")
    solve_transient(nl, t_end=10.0, dt=1.0)
    vs = bp.model.cell_voltages()
    ts = bp.model.cell_temperatures()
    assert len(vs) == bp.model.n_series
    assert all(len(row) == bp.model.n_parallel for row in vs)
    assert all(2.0 < v < 5.0 for row in vs for v in row)
    # Cells started with a 10% SOC spread → per-cell V should differ
    flat = [v for row in vs for v in row]
    assert max(flat) - min(flat) > 1e-3
    # Temperature placeholder defaults to 25 °C across the pack.
    assert all(t == 25.0 for row in ts for t in row)
    # Pack-level current is exposed once.
    assert bp.model.I_pack == bp.model._I


def test_pack_thermal_hook_can_be_installed_and_called_per_cell():
    pack = BatteryPackModel(n_series=2, n_parallel=2,
                            cell_factory=None, soc_init_spread=0.0,
                            balancer="None")

    class _ThermalStub:
        def __init__(self):
            self.calls = 0
        def update(self, I_cell, V_cell, dt, t):
            self.calls += 1
            return 30.0 + I_cell  # arbitrary deterministic mapping

    pack.set_thermal_model(_ThermalStub)
    pack.update(I=2.0, dt=1.0, t=0.0)
    flat = [c for row in pack.cells for c in row]
    assert all(c.thermal_model is not None for c in flat)
    assert all(c.thermal_model.calls == 1 for c in flat)
    # I_string = 2/2 = 1 → T_cell = 30 + 1 = 31
    assert all(abs(c.T_cell - 31.0) < 1e-9 for c in flat)


def test_passive_v1_requires_continuous_rest_before_starting_new_slot():
    bal = PassiveBalancerV1(soc_enable=0.0, dev_min=0.05,
                            soc_drop=10.0, I_bal=1.0,
                            pack_pause=0.0, pack_resume=0.0,
                            rest_min=60.0, I_rest=0.05)

    class _Cell:
        def __init__(self, soc):
            self.soc = soc
            self.capacity_Ah = 1.0

    cells = [_Cell(0.60), _Cell(0.50)]
    # Pack drawing 5 A → not rest. No bleed should start, ever.
    for _ in range(120):
        out = bal.bleed_currents(cells, dt=1.0, t=0.0, I_pack=5.0)
        assert out == [0.0, 0.0]
    # Switch to rest (I_pack ~ 0). 59 s rest is not enough yet.
    for _ in range(59):
        out = bal.bleed_currents(cells, dt=1.0, t=0.0, I_pack=0.0)
        assert out == [0.0, 0.0]
    # 60th rest second crosses rest_min → eligible cell starts bleeding.
    out = bal.bleed_currents(cells, dt=1.0, t=0.0, I_pack=0.0)
    assert out[0] == 1.0


def test_passive_v1_active_slot_continues_when_rest_breaks():
    # Slot length: soc_drop=0.001, I_bal=1A, Q=1Ah → 3.6 s.
    bal = PassiveBalancerV1(soc_enable=0.0, dev_min=0.05,
                            soc_drop=0.001, I_bal=1.0,
                            pack_pause=0.0, pack_resume=0.0,
                            rest_min=10.0, I_rest=0.05)

    class _Cell:
        def __init__(self, soc):
            self.soc = soc
            self.capacity_Ah = 1.0

    cells = [_Cell(0.60), _Cell(0.50)]
    # Accumulate enough rest to start a bleed slot.
    for _ in range(10):
        bal.bleed_currents(cells, dt=1.0, t=0.0, I_pack=0.0)
    out = bal.bleed_currents(cells, dt=1.0, t=0.0, I_pack=0.0)
    assert out[0] == 1.0  # slot started
    # Now break rest with a big load — active slot must keep running.
    for _ in range(2):
        out = bal.bleed_currents(cells, dt=1.0, t=0.0, I_pack=20.0)
        assert out[0] == 1.0
