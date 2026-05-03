import csv
import io
import sys
import tempfile
from pathlib import Path

import pytest

from batsim.cli import build_parser, main as cli_main
import batsim.plugins.builtin  # noqa: F401
import batsim.soc as _soc  # noqa: F401  (registers built-in SOC)
from batsim.plugins import discover

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
    assert "INR18650-25R" in out


def test_cli_list_soc(capsys):
    rc, out = run_cli(["list-soc"], capsys)
    assert rc == 0
    assert "CoulombCounter" in out
    assert "OCVLookup" in out


def test_cli_cell_test(capsys, tmpdir_safe):
    csvp = tmpdir_safe / "out.csv"
    rc, out = run_cli(["cell-test", "--cell", "INR18650-25R",
                       "--r-load", "10.0", "--t-end", "5.0", "--dt", "0.5",
                       "--csv", str(csvp)], capsys)
    assert rc == 0
    assert csvp.exists()
    assert "final V(n1)" in out


def test_cli_run_dc(capsys):
    proj = Path(__file__).parents[1] / "resources" / "examples" / "battery_discharge.batsim"
    rc, out = run_cli(["run", str(proj), "--dc"], capsys)
    assert rc == 0
    assert "V(" in out


def test_cli_sweep(capsys, tmpdir_safe):
    cfg = tmpdir_safe / "sweep.json"
    cfg.write_text("""{
      "runner": "battery_profile_run",
      "base":   {"cell": "INR18650-25R", "I_profile": 1.0,
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
                       "--cell", "INR18650-25R",
                       "--current", "0.5", "--t-end", "120", "--dt", "1.0"],
                      capsys)
    assert rc == 0
    assert "RMSE" in out
    assert "SimpleEKF" in out
    assert "SmoothedCC" in out
