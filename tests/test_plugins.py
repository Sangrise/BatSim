import json
import tempfile
from pathlib import Path

import batsim_core.plugins.builtin  # registers built-ins
from batsim_core.plugins import discover, list_battery_models, make_battery
from batsim_core.plugins.registry import (BATTERY_MODELS, CELL_LIBRARY,
                                     register_battery_model)
from batsim_core.models.base import BatteryModel


def test_builtin_models_registered():
    assert "Rint" in BATTERY_MODELS
    assert "Thevenin" in BATTERY_MODELS
    assert "n-RC" in BATTERY_MODELS
    assert "DataDriven" in BATTERY_MODELS
    assert "SPM" in BATTERY_MODELS


def test_data_cells_discovered():
    discover()  # scans repo data/
    assert "NCM-50Ah-csv" in CELL_LIBRARY


def test_make_battery_from_cell():
    discover()
    bat = make_battery(cell="NCM-50Ah-csv")
    v0 = bat.terminal_voltage(0, None)
    assert 4.0 < v0 < 4.3


def test_user_decorator_registration():
    @register_battery_model("TestPlugin")
    class P(BatteryModel):
        def terminal_voltage(self, t, dt):
            return 3.14
    assert "TestPlugin" in list_battery_models()
    bat = make_battery(model_name="TestPlugin")
    assert bat.terminal_voltage(0, None) == 3.14


def test_data_only_plugin_via_tmp(monkeypatch):
    """Drop a JSON file in a user data dir and verify it shows up."""
    base = Path(tempfile.mkdtemp(prefix="batsim_test_"))
    user_dir = base / ".batsim" / "data" / "cells"
    user_dir.mkdir(parents=True)
    cell = {
        "name": "TmpCell-X",
        "model": "DataDriven",
        "params": {
            "capacity_Ah": 1.0, "soc0": 0.5, "R0": 0.01,
            "RC_pairs": [], "ocv_table": [[0.0, 3.0], [1.0, 4.2]],
        },
    }
    (user_dir / "tmp.json").write_text(json.dumps(cell))
    monkeypatch.setattr(Path, "home", lambda: base)
    discover()
    assert "TmpCell-X" in CELL_LIBRARY
    bat = make_battery(cell="TmpCell-X")
    assert abs(bat.terminal_voltage(0, None) - 3.6) < 1e-9  # OCV(0.5)


def test_csv_folder_cell_builtin():
    """CSV-folder cell shipped under data/cells/<name>/ is discovered and
    builds a working battery model."""
    discover()
    assert "NCM-50Ah-csv" in CELL_LIBRARY
    bat = make_battery(cell="NCM-50Ah-csv")
    v0 = bat.terminal_voltage(0, None)
    assert 4.0 < v0 < 4.3   # SOC=1 → ~4.20 V


def test_csv_folder_cell_user_dir(monkeypatch):
    """A user can drop a CSV-folder cell under ~/.batsim/data/cells/<name>/."""
    base = Path(tempfile.mkdtemp(prefix="batsim_csvcell_"))
    folder = base / ".batsim" / "data" / "cells" / "TmpCsvCell"
    folder.mkdir(parents=True)
    (folder / "meta.csv").write_text(
        "key,value\nname,TmpCsvCell\nmodel,DataDriven\n"
        "capacity_Ah,1.0\nsoc0,0.5\nR0,0.01\n", encoding="utf-8")
    (folder / "ocv.csv").write_text(
        "soc,V_oc\n0.0,3.0\n1.0,4.2\n", encoding="utf-8")
    (folder / "rc_pairs.csv").write_text("R,C\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: base)
    discover()
    assert "TmpCsvCell" in CELL_LIBRARY
    bat = make_battery(cell="TmpCsvCell")
    assert abs(bat.terminal_voltage(0, None) - 3.6) < 1e-9


