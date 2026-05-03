import numpy as np
from batsim.soc import (SOC_ALGORITHMS, load_from_path, make_soc,
                        register_soc_algorithm, list_soc_algorithms)
from batsim.sim import battery_profile_run
from pathlib import Path
import batsim.plugins.builtin  # noqa: F401
from batsim.plugins import discover

discover()


def test_builtin_soc_registered():
    assert "CoulombCounter" in SOC_ALGORITHMS
    assert "OCVLookup" in SOC_ALGORITHMS


def test_load_external_script():
    script = Path(__file__).parents[1] / "examples" / "external_soc_example.py"
    new = load_from_path(script)
    # SimpleEKF is decorated; SmoothedCC is a function (also decorated)
    assert "SimpleEKF" in SOC_ALGORITHMS
    assert "SmoothedCC" in SOC_ALGORITHMS


def test_external_soc_runs_and_tracks_truth():
    script = Path(__file__).parents[1] / "examples" / "external_soc_example.py"
    load_from_path(script)
    truth = battery_profile_run(cell="INR18650-25R", I_profile=1.0,
                                t_end=600.0, dt=1.0)
    algo = make_soc("SimpleEKF", capacity_Ah=truth["model"].capacity_Ah,
                    soc0=1.0)
    est = []
    for k in range(len(truth["t"])):
        est.append(algo.step(I=float(truth["I"][k]),
                             V=float(truth["V"][k]),
                             dt=1.0))
    err = abs(est[-1] - truth["SOC"][-1])
    # Lightweight EKF should track within a few % over 10 minutes
    assert err < 0.1


def test_function_style_algorithm_works():
    script = Path(__file__).parents[1] / "examples" / "external_soc_example.py"
    load_from_path(script)
    algo = make_soc("SmoothedCC", cap=2.5, soc=1.0, alpha=1.0)  # no smoothing
    soc = algo.step(I=1.0, V=4.0, dt=3600.0)
    # 1 A * 1 h / 2.5 Ah = 0.4 SOC reduction -> 0.6
    assert 0.55 < soc < 0.65
