import csv
import io
import sys
import tempfile
from pathlib import Path

import pytest

from batsim_core.cli import build_parser, main as cli_main
import batsim_core.plugins.builtin  # noqa: F401
import batsim_core.soc as _soc  # noqa: F401  (registers built-in SOC)
from batsim_core.plugins import discover

discover()


@pytest.fixture
def tmpdir_safe():
    """Workaround for blocked system temp dir on this machine."""
    d = Path(tempfile.mkdtemp(prefix="batsim_cli_test_"))
    yield d


def run_cli(argv, capsys):
    rc = cli_main(argv)
    out = capsys.readouterr().out
    return rc, out


def test_cli_list_models(capsys):
    rc, out = run_cli(["list-models"], capsys)
    assert rc == 0
    assert "Thevenin" in out
    assert "Rint" in out


def test_cli_list_cells(capsys):
    rc, out = run_cli(["list-cells"], capsys)
    assert rc == 0
    assert "NCM-50Ah-csv" in out


def test_cli_list_soc(capsys):
    rc, out = run_cli(["list-soc"], capsys)
    assert rc == 0
    assert "CoulombCounter" in out
    assert "OCVLookup" in out


def test_cli_catalog_basic_json(capsys):
    rc, out = run_cli(["catalog", "--level", "basic", "--json"], capsys)
    assert rc == 0
    assert '"level": "basic"' in out
    assert '"PCS"' in out
    assert '"JUNCTION"' not in out


def test_cli_cell_test(capsys, tmpdir_safe):
    csvp = tmpdir_safe / "out.csv"
    rc, out = run_cli(["cell-test", "--cell", "NCM-50Ah-csv",
                       "--r-load", "10.0", "--t-end", "5.0", "--dt", "0.5",
                       "--csv", str(csvp)], capsys)
    assert rc == 0
    assert csvp.exists()
    assert "final V(n1)" in out


def test_cli_run_dc(capsys):
    proj = Path(__file__).parents[1] / "assets" / "examples" / "battery_discharge.batsim"
    rc, out = run_cli(["run", str(proj), "--dc"], capsys)
    assert rc == 0
    assert "V(" in out


def test_cli_run_json(capsys):
    proj = Path(__file__).parents[1] / "assets" / "examples" / "battery_discharge.batsim"
    rc, out = run_cli(["run", str(proj), "--t-end", "0.01", "--dt", "0.01",
                       "--json"], capsys)
    assert rc == 0
    assert '"kind": "transient"' in out
    assert '"final_voltages"' in out


def test_cli_inspect_json(capsys):
    proj = Path(__file__).parents[1] / "assets" / "examples" / "battery_discharge.batsim"
    rc, out = run_cli(["inspect", str(proj), "--json"], capsys)
    assert rc == 0
    assert '"components"' in out
    assert '"BATTERY"' in out


def test_cli_validate_dc_json(capsys):
    proj = Path(__file__).parents[1] / "assets" / "examples" / "battery_discharge.batsim"
    rc, out = run_cli(["validate", str(proj), "--dc", "--json"], capsys)
    assert rc == 0
    assert '"ok": true' in out
    assert '"dc_voltages"' in out


def test_cli_sweep(capsys, tmpdir_safe):
    cfg = tmpdir_safe / "sweep.json"
    cfg.write_text("""{
      "runner": "battery_profile_run",
      "base":   {"cell": "NCM-50Ah-csv", "I_profile": 1.0,
                 "t_end": 5.0, "dt": 0.5},
      "grid":   {"model_name": ["Rint", "Thevenin"]},
      "metric": "min_voltage"
    }""")
    out_csv = tmpdir_safe / "sweep.csv"
    rc, out = run_cli(["sweep", str(cfg), "--csv", str(out_csv)], capsys)
    assert rc == 0
    assert out_csv.exists()


def test_cli_soc_eval_with_external_script(capsys):
    script = Path(__file__).parents[1] / "examples" / "external_soc_example.py"
    rc, out = run_cli(["soc-eval", "--script", str(script),
                       "--algorithm", "CoulombCounter", "SimpleEKF",
                       "SmoothedCC", "OCVLookup",
                       "--cell", "NCM-50Ah-csv",
                       "--current", "0.5", "--t-end", "120", "--dt", "1.0"],
                      capsys)
    assert rc == 0
    assert "RMSE" in out
    assert "SimpleEKF" in out
    assert "SmoothedCC" in out


def test_cli_route_check(capsys):
    rc, out = run_cli(["route-check"], capsys)
    assert rc == 0
    assert "route-check passed" in out


def test_cli_blocks_roundtrip(capsys, tmpdir_safe, monkeypatch):
    import batsim_core.io.blocks as blocks
    monkeypatch.setattr(blocks, "BLOCKS_DIR", tmpdir_safe / "blocks")
    block_src = tmpdir_safe / "module.json"
    block_src.write_text("""{
      "components": [
        {"id": "R1", "kind": "R", "params": {"R": 5.0},
         "pins": [null, null], "pos": [0, 0], "rotation": 0,
         "tap_pin": null}
      ],
      "wires": []
    }""", encoding="utf-8")
    rc, out = run_cli(["blocks", "import", str(block_src), "--name", "Load"], capsys)
    assert rc == 0
    assert "imported" in out
    rc, out = run_cli(["blocks", "list", "--json"], capsys)
    assert rc == 0
    assert '"Load"' in out
    rc, out = run_cli(["blocks", "show", "Load"], capsys)
    assert rc == 0
    assert '"R"' in out
    exported = tmpdir_safe / "exported.json"
    rc, out = run_cli(["blocks", "export", "Load", str(exported)], capsys)
    assert rc == 0
    assert exported.exists()


