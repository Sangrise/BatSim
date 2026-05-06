"""BatSim CLI entry point.

Subcommands:
    ui                    Launch the GUI
    list-models           List registered battery models
    list-cells            List discovered cell data files
    list-bms              List BMS profiles
    list-soc              List registered SOC algorithms
    run     <project>     Run a .batsim project headlessly (transient)
    cell-test             Discharge a cell into a fixed load and dump CSV
    sweep   <config>      Parameter sweep from a YAML/JSON config
    soc-eval              Evaluate one or more SOC algorithms vs. truth
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def _load_plugins():
    """Import built-in plugins and discover external ones once."""
    import batsim.plugins.builtin  # noqa: F401
    import batsim.soc  # noqa: F401  (registers built-in SOC baselines)
    from batsim.plugins import discover
    return discover()


# --- Sub-command implementations -------------------------------------------

def cmd_ui(args):
    from batsim.app import main
    return main()


def cmd_list_models(args):
    from batsim.plugins import list_battery_models
    for n in list_battery_models():
        print(n)
    return 0


def cmd_list_cells(args):
    from batsim.plugins import list_cells
    for n in list_cells():
        print(n)
    return 0


def cmd_list_bms(args):
    from batsim.plugins import list_bms_profiles
    from batsim.plugins.registry import BMS_BLOCKS
    import batsim.bms  # noqa: F401  — triggers built-in BMS block registration
    profiles = list_bms_profiles()
    if profiles:
        print("# profiles")
        for n in profiles:
            print(n)
    if BMS_BLOCKS:
        print("# blocks")
        for n in sorted(BMS_BLOCKS.keys()):
            print(n)
    return 0


def cmd_list_soc(args):
    from batsim.soc import list_soc_algorithms
    for n in list_soc_algorithms():
        print(n)
    return 0


def cmd_run(args):
    from batsim.io.project import load_project
    from batsim.engine.netlist import from_graph, probe_map
    from batsim.engine.nonlinear import solve_dc, solve_transient
    from batsim.plugins.registry import make_battery

    graph = load_project(args.project)
    for c in graph["components"]:
        if c["kind"] == "BATTERY":
            p = c["params"]
            cell = p.get("cell") or None
            model_name = p.get("model")
            kwargs = {k: v for k, v in p.items() if k not in ("model", "cell")}
            c["model"] = make_battery(model_name=model_name, cell=cell, **kwargs)

    nl = from_graph(graph)
    if args.dc:
        sys_, x = solve_dc(nl)
        v = sys_.node_voltages(x)
        for n, val in sorted(v.items()):
            print(f"V({n}) = {val:.6f}")
        return 0

    res = solve_transient(nl, t_end=args.t_end, dt=args.dt)
    aliases = probe_map(graph)
    if args.csv:
        _write_transient_csv(res, args.csv, aliases=aliases)
        print(f"wrote {args.csv}")
    else:
        print(f"t_end = {res['t'][-1]:.6f} s, steps = {len(res['t'])}")
        for n, arr in res["V"].items():
            print(f"  V({n})[end] = {arr[-1]:.6f}")
        for n, arr in res["I"].items():
            print(f"  I({n})[end] = {arr[-1]:.6f}")
    return 0


def _write_transient_csv(res, path, aliases=None):
    import csv
    aliases = aliases or {"voltages": {}, "currents": {}}
    cols = ["t"]
    series: list = []
    used_v_nodes: set[str] = set()
    used_i_names: set[str] = set()
    for pid, info in aliases.get("voltages", {}).items():
        if isinstance(info, tuple):
            npos, nneg = info
            arr_p = res["V"].get(npos)
            if arr_p is None:
                continue
            if nneg in (None, "0"):
                arr = list(arr_p)
            else:
                arr_n = res["V"].get(nneg)
                arr = list(arr_p) if arr_n is None \
                    else [a - b for a, b in zip(arr_p, arr_n)]
            cols.append(f"V({pid})")
            series.append(arr)
            used_v_nodes.add(npos)
            if nneg not in (None, "0"):
                used_v_nodes.add(nneg)
        else:
            arr = res["V"].get(info)
            if arr is not None:
                cols.append(f"V({pid})")
                series.append(arr)
                used_v_nodes.add(info)
    for pid, vsname in aliases.get("currents", {}).items():
        arr = res["I"].get(vsname)
        if arr is not None:
            cols.append(f"I({pid})")
            series.append(arr)
            used_i_names.add(vsname)
    for n, arr in res["V"].items():
        if n in used_v_nodes:
            continue
        cols.append(f"V({n})")
        series.append(arr)
    for n, arr in res["I"].items():
        if n in used_i_names:
            continue
        cols.append(f"I({n})")
        series.append(arr)
    rows = list(zip(res["t"], *series))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)


def cmd_cell_test(args):
    from batsim.sim import cell_under_load
    res = cell_under_load(cell=args.cell, model_name=args.model,
                          R_load_ohm=args.r_load,
                          t_end=args.t_end, dt=args.dt)
    if args.csv:
        _write_transient_csv(res, args.csv)
        print(f"wrote {args.csv}")
    print(f"final V(n1) = {res['V']['n1'][-1]:.4f} V, "
          f"final SOC = {res['model'].soc:.4f}")
    return 0


def cmd_sweep(args):
    """Run a parameter sweep from a JSON/YAML config:

    {
      "runner": "battery_profile_run",       # or "cell_under_load"
      "base":   {"cell": "INR18650-25R", "t_end": 600, "dt": 1.0,
                 "I_profile": 1.0},
      "grid":   {"R0": [0.02, 0.03, 0.04],
                 "soc0": [0.8, 1.0]},
      "metric": "min_voltage"                # or "energy_Wh"
    }
    """
    cfg = _load_config(args.config)
    from batsim.sim import (battery_profile_run, cell_under_load,
                            parameter_sweep)
    runners = {"battery_profile_run": battery_profile_run,
               "cell_under_load": cell_under_load}
    runner = runners[cfg.get("runner", "battery_profile_run")]
    metric = _resolve_metric(cfg.get("metric", "min_voltage"))
    rows = parameter_sweep(base_kwargs=cfg.get("base", {}),
                           grid=cfg.get("grid", {}),
                           metric=metric, runner=runner)
    if args.csv:
        import csv
        if rows:
            keys = list(rows[0]["params"].keys())
            with open(args.csv, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(keys + ["metric"])
                for r in rows:
                    w.writerow([r["params"][k] for k in keys] + [r["metric"]])
            print(f"wrote {args.csv} ({len(rows)} rows)")
    # Always show top-5 by metric
    rows_sorted = sorted(rows, key=lambda r: r["metric"], reverse=args.maximise)
    print(f"\nTop {min(5, len(rows_sorted))} (maximise={args.maximise}):")
    for r in rows_sorted[:5]:
        print(f"  metric={r['metric']:.6f}  params={r['params']}")
    return 0


def cmd_soc_eval(args):
    """Run a chosen SOC algorithm against a truth battery model and report RMSE."""
    from batsim.soc import load_from_path, make_soc, list_soc_algorithms
    from batsim.sim import battery_profile_run

    if args.script:
        new = load_from_path(args.script)
        print(f"loaded from {args.script}: {new}")

    if not args.algorithm:
        print("Available algorithms:")
        for n in list_soc_algorithms():
            print(f"  {n}")
        return 0

    # Build a current profile
    if args.profile_csv:
        import csv as _csv
        with open(args.profile_csv, encoding="utf-8") as f:
            rdr = _csv.reader(f)
            next(rdr, None)
            prof = np.array([float(row[0]) for row in rdr], dtype=float)
        I_profile = prof
        t_end = (len(prof) - 1) * args.dt
    else:
        I_profile = float(args.current)  # constant current
        t_end = args.t_end

    truth = battery_profile_run(cell=args.cell, model_name=args.model,
                                I_profile=I_profile, t_end=t_end, dt=args.dt)

    algos = args.algorithm
    estimates: dict[str, np.ndarray] = {}
    for alg_name in algos:
        algo = make_soc(alg_name,
                        capacity_Ah=truth["model"].capacity_Ah,
                        soc0=args.soc0)
        est = np.zeros_like(truth["t"])
        est[0] = getattr(algo, "soc", args.soc0)
        for k in range(1, len(truth["t"])):
            est[k] = algo.step(I=float(truth["I"][k]),
                               V=float(truth["V"][k]),
                               dt=args.dt)
        estimates[alg_name] = est

    print(f"\nTruth final SOC: {truth['SOC'][-1]:.4f}")
    print(f"{'Algorithm':<24} {'RMSE':>10} {'final':>10}")
    for nm, est in estimates.items():
        rmse = float(np.sqrt(np.mean((est - truth["SOC"]) ** 2)))
        print(f"{nm:<24} {rmse:>10.5f} {est[-1]:>10.4f}")

    if args.csv:
        import csv as _csv
        cols = ["t", "I", "V", "SOC_truth"] + list(estimates.keys())
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(cols)
            for k in range(len(truth["t"])):
                row = [truth["t"][k], truth["I"][k], truth["V"][k],
                       truth["SOC"][k]]
                row += [estimates[a][k] for a in estimates]
                w.writerow(row)
        print(f"wrote {args.csv}")
    return 0


# --- Helpers ----------------------------------------------------------------

def _load_config(path: str) -> dict:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix in (".yaml", ".yml"):
        import yaml
        return yaml.safe_load(text)
    return json.loads(text)


def _resolve_metric(name):
    if callable(name):
        return name
    if name == "min_voltage":
        return lambda res: float(np.min(res["V"]))
    if name == "final_soc":
        return lambda res: float(res["SOC"][-1])
    if name == "energy_Wh":
        return lambda res: float(
            np.trapz(res["V"] * res["I"], res["t"]) / 3600.0)
    raise KeyError(f"Unknown metric: {name}")


# --- argparse plumbing ------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="batsim",
                                description="BatSim — battery & BMS circuit simulator (CLI)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ui", help="Launch the GUI").set_defaults(func=cmd_ui)
    sub.add_parser("list-models", help="List battery models"
                   ).set_defaults(func=cmd_list_models)
    sub.add_parser("list-cells", help="List discovered cell data files"
                   ).set_defaults(func=cmd_list_cells)
    sub.add_parser("list-bms", help="List BMS profiles"
                   ).set_defaults(func=cmd_list_bms)
    sub.add_parser("list-soc", help="List SOC algorithms"
                   ).set_defaults(func=cmd_list_soc)

    pr = sub.add_parser("run", help="Run a .batsim project headlessly")
    pr.add_argument("project")
    pr.add_argument("--t-end", type=float, default=1.0)
    pr.add_argument("--dt", type=float, default=1e-3)
    pr.add_argument("--dc", action="store_true", help="DC operating point only")
    pr.add_argument("--csv", help="Write transient series to this CSV")
    pr.set_defaults(func=cmd_run)

    pc = sub.add_parser("cell-test", help="Discharge a cell into a fixed load")
    pc.add_argument("--cell", default=None)
    pc.add_argument("--model", default=None)
    pc.add_argument("--r-load", type=float, default=1.0)
    pc.add_argument("--t-end", type=float, default=60.0)
    pc.add_argument("--dt", type=float, default=0.1)
    pc.add_argument("--csv")
    pc.set_defaults(func=cmd_cell_test)

    ps = sub.add_parser("sweep", help="Parameter sweep from a JSON/YAML config")
    ps.add_argument("config")
    ps.add_argument("--csv")
    ps.add_argument("--maximise", action="store_true",
                    help="Sort results descending (default: ascending)")
    ps.set_defaults(func=cmd_sweep)

    pe = sub.add_parser("soc-eval", help="Evaluate SOC algorithm(s)")
    pe.add_argument("--script", help="Path to .py file with SOC algorithms")
    pe.add_argument("--algorithm", nargs="*", default=[],
                    help="Names to evaluate (omit to list available)")
    pe.add_argument("--cell", default=None)
    pe.add_argument("--model", default=None)
    pe.add_argument("--current", type=float, default=1.0,
                    help="Constant discharge current (A) if no profile CSV")
    pe.add_argument("--profile-csv", help="CSV with one column of currents (A) per dt")
    pe.add_argument("--t-end", type=float, default=3600.0)
    pe.add_argument("--dt", type=float, default=1.0)
    pe.add_argument("--soc0", type=float, default=1.0)
    pe.add_argument("--csv", help="Write per-step truth + estimates to CSV")
    pe.set_defaults(func=cmd_soc_eval)

    return p


def main(argv: list[str] | None = None) -> int:
    _load_plugins()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
