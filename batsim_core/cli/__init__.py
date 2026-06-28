"""BatSim CLI entry point.

Subcommands:
    ui                    Launch the GUI
    list-models           List registered battery models
    list-cells            List discovered cell data files
    list-bms              List BMS profiles
    list-soc              List registered SOC algorithms
    catalog               List schematic components by UI level
    inspect <project>     Summarise a .batsim project
    validate <project>    Build/optionally solve a project for CI/automation
    run     <project>     Run a .batsim project headlessly (transient)
    cell-test             Discharge a cell into a fixed load and dump CSV
    sweep   <config>      Parameter sweep from a YAML/JSON config
    soc-eval              Evaluate one or more SOC algorithms vs. truth
    route-check           Check schematic wire routing overlap cases
    blocks                Manage reusable schematic blocks
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np


def _load_plugins():
    """Import built-in plugins and discover external ones once."""
    import batsim_core.plugins.builtin  # noqa: F401
    import batsim_core.soc  # noqa: F401  (registers built-in SOC baselines)
    from batsim_core.plugins import discover
    return discover()


# --- Sub-command implementations -------------------------------------------

def cmd_ui(args):
    from batsim_core.app import main
    return main()


def cmd_list_models(args):
    from batsim_core.plugins import list_battery_models
    for n in list_battery_models():
        print(n)
    return 0


def cmd_list_cells(args):
    from batsim_core.plugins import list_cells
    for n in list_cells():
        print(n)
    return 0


def cmd_list_bms(args):
    from batsim_core.plugins import list_bms_profiles
    from batsim_core.plugins.registry import BMS_BLOCKS
    import batsim_core.bms  # noqa: F401  — triggers built-in BMS block registration
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
    from batsim_core.soc import list_soc_algorithms
    for n in list_soc_algorithms():
        print(n)
    return 0


def cmd_catalog(args):
    from batsim_core.components.groups import grouped_catalog
    groups = grouped_catalog(args.level)
    if args.json:
        print(json.dumps({"level": args.level, "groups": groups},
                         ensure_ascii=False, indent=2))
    else:
        for group in groups:
            print(f"# {group['group']}")
            for item in group["items"]:
                print(f"{item['kind']:<8} {item['label']}  pins={item['pins']}")
    return 0


def _prepare_project_graph(project: str) -> dict:
    from batsim_core.io.project import load_project
    from batsim_core.plugins.registry import make_battery

    graph = load_project(project)
    for c in graph.get("components", []):
        if c.get("kind") == "BATTERY":
            p = c.get("params", {})
            cell = p.get("cell") or None
            model_name = p.get("model")
            kwargs = {k: v for k, v in p.items() if k not in ("model", "cell")}
            c["model"] = make_battery(model_name=model_name, cell=cell, **kwargs)
    return graph


def _project_summary(graph: dict) -> dict:
    comps = graph.get("components", [])
    wires = graph.get("wires", [])
    kinds: dict[str, int] = {}
    ids: set[str] = set()
    duplicate_ids: list[str] = []
    for c in comps:
        kind = c.get("kind", "")
        kinds[kind] = kinds.get(kind, 0) + 1
        cid = c.get("id", "")
        if cid in ids:
            duplicate_ids.append(cid)
        ids.add(cid)
    probes = [c.get("id") for c in comps
              if c.get("kind") in ("PROBE", "IPROBE")]
    anchors = [c.get("id") for c in comps
               if c.get("kind") in ("GND", "BUS", "GRID", "PCS")]
    warnings: list[str] = []
    if duplicate_ids:
        warnings.append("duplicate component ids: " + ", ".join(duplicate_ids))
    if not anchors:
        warnings.append("no explicit GND/BUS/GRID/PCS anchor; auto-ground fallback will be used")
    for c in comps:
        if c.get("kind") == "PCS":
            mode = str(c.get("params", {}).get("mode", ""))
            if mode in ("CYCLE", "CC", "CP", "CCCV", "CPCV"):
                warnings.append(
                    f"{c.get('id')}: PCS {mode} uses the current legacy sign workaround")
    return {
        "components": len(comps),
        "wires": len(wires),
        "kinds": dict(sorted(kinds.items())),
        "probes": probes,
        "anchors": anchors,
        "warnings": warnings,
    }


def cmd_inspect(args):
    graph = _prepare_project_graph(args.project)
    summary = _project_summary(graph)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"components: {summary['components']}")
        print(f"wires: {summary['wires']}")
        for kind, count in summary["kinds"].items():
            print(f"  {kind}: {count}")
        if summary["probes"]:
            print("probes: " + ", ".join(summary["probes"]))
        if summary["anchors"]:
            print("anchors: " + ", ".join(summary["anchors"]))
        for warning in summary["warnings"]:
            print(f"warning: {warning}")
    return 0


def cmd_validate(args):
    from batsim_core.engine.netlist import from_graph
    from batsim_core.engine.nonlinear import solve_dc

    result = {"ok": True, "errors": [], "warnings": [], "summary": None}
    try:
        graph = _prepare_project_graph(args.project)
        result["summary"] = _project_summary(graph)
        result["warnings"] = list(result["summary"]["warnings"])
        nl = from_graph(graph)
        result["netlist_elements"] = len(nl.elements)
        result["netlist_nodes"] = len(nl.nodes)
        if args.dc:
            sys_, x = solve_dc(nl)
            result["dc_voltages"] = sys_.node_voltages(x)
    except Exception as exc:  # noqa: BLE001
        result["ok"] = False
        result["errors"].append(str(exc))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("ok" if result["ok"] else "failed")
        if result.get("netlist_elements") is not None:
            print(f"netlist: {result['netlist_elements']} elements, "
                  f"{result['netlist_nodes']} nodes")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
        for error in result["errors"]:
            print(f"error: {error}")
    return 0 if result["ok"] else 1


def cmd_run(args):
    from batsim_core.engine.netlist import from_graph, probe_map
    from batsim_core.engine.nonlinear import solve_dc, solve_transient

    graph = _prepare_project_graph(args.project)
    nl = from_graph(graph)
    if args.dc:
        sys_, x = solve_dc(nl)
        v = sys_.node_voltages(x)
        if args.json:
            print(json.dumps({"kind": "dc", "voltages": v},
                             ensure_ascii=False, indent=2))
            return 0
        for n, val in sorted(v.items()):
            print(f"V({n}) = {val:.6f}")
        return 0

    res = solve_transient(nl, t_end=args.t_end, dt=args.dt)
    aliases = probe_map(graph)
    if args.csv:
        _write_transient_csv(res, args.csv, aliases=aliases)
        print(f"wrote {args.csv}")
    elif args.json:
        print(json.dumps({
            "kind": "transient",
            "t_end": float(res["t"][-1]),
            "steps": len(res["t"]),
            "final_voltages": {n: float(arr[-1])
                               for n, arr in res["V"].items()},
            "final_currents": {n: float(arr[-1])
                               for n, arr in res["I"].items()},
            "probes": aliases,
        }, ensure_ascii=False, indent=2))
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
    from batsim_core.sim import cell_under_load
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
    from batsim_core.sim import (battery_profile_run, cell_under_load,
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
    from batsim_core.soc import load_from_path, make_soc, list_soc_algorithms
    from batsim_core.sim import battery_profile_run

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


def cmd_route_check(args):
    """Run deterministic schematic-routing overlap checks."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QPointF
    from PyQt6.QtWidgets import QApplication

    from batsim_core.ui.canvas.scene import SchematicScene
    from batsim_core.ui.canvas.wire_item import WireItem
    from batsim_core.ui.canvas.wire_routing import _seg_in_rect
    from batsim_core.ui.fonts import setup_application_font

    app = QApplication.instance() or QApplication(sys.argv)
    setup_application_font(app)
    cases = [
        ("central-blocker", "R", QPointF(-100, 0), 1,
         "R", QPointF(100, 0), 0,
         [("R", QPointF(0, 0))]),
        ("near-source-dogleg", "BATTERY", QPointF(-180, -40), 1,
         "C", QPointF(180, 120), 0,
         [("BATPACK", QPointF(-100, 20))]),
        ("destination-side-grid", "BATPACK", QPointF(-200, -140), 1,
         "BUS", QPointF(60, 80), 1,
         [("BATTERY", QPointF(120, -40))]),
    ]
    failures: list[str] = []
    for name, ak, apos, ap, bk, bpos, bp, blocker_specs in cases:
        sc = SchematicScene()
        a = sc.add_component(ak, apos)
        b = sc.add_component(bk, bpos)
        blockers = [sc.add_component(k, p) for k, p in blocker_specs]
        w = WireItem(a, ap, b, bp)
        sc.addItem(w)
        sc._wires.append(w)
        w.refresh()
        pts = [QPointF(w._path.elementAt(i).x, w._path.elementAt(i).y)
               for i in range(w._path.elementCount())]
        for blocker in blockers:
            br = blocker.sceneBoundingRect()
            if any(_seg_in_rect(p1, p2, br)
                   for p1, p2 in zip(pts, pts[1:])):
                failures.append(f"{name}: wire crosses {blocker.cid}")
    if failures:
        for failure in failures:
            print(failure)
        return 1
    print(f"route-check passed ({len(cases)} cases)")
    return 0


def cmd_blocks(args):
    from batsim_core.io.blocks import (BLOCKS_DIR, export_block, import_block,
                                  list_blocks, load_block)

    if args.blocks_cmd == "list":
        names = list_blocks()
        if args.json:
            print(json.dumps({"dir": str(BLOCKS_DIR), "blocks": names},
                             ensure_ascii=False, indent=2))
        else:
            for name in names:
                print(name)
        return 0
    if args.blocks_cmd == "show":
        graph = load_block(args.name)
        if args.json:
            print(json.dumps(graph, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(_project_summary(graph), ensure_ascii=False,
                             indent=2))
        return 0
    if args.blocks_cmd == "import":
        path = import_block(args.path, args.name)
        print(f"imported {path}")
        return 0
    if args.blocks_cmd == "export":
        path = export_block(args.name, args.path)
        print(f"exported {path}")
        return 0
    raise SystemExit("missing blocks subcommand")


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
    pcatalog = sub.add_parser("catalog", help="List schematic components")
    pcatalog.add_argument("--level", choices=("basic", "advanced", "all"),
                          default="basic")
    pcatalog.add_argument("--json", action="store_true")
    pcatalog.set_defaults(func=cmd_catalog)
    sub.add_parser("route-check", help="Check schematic wire routing overlaps"
                   ).set_defaults(func=cmd_route_check)

    pi = sub.add_parser("inspect", help="Summarise a .batsim project")
    pi.add_argument("project")
    pi.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON")
    pi.set_defaults(func=cmd_inspect)

    pv = sub.add_parser("validate", help="Validate a .batsim project")
    pv.add_argument("project")
    pv.add_argument("--dc", action="store_true",
                    help="Also solve the DC operating point")
    pv.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON")
    pv.set_defaults(func=cmd_validate)

    pb = sub.add_parser("blocks", help="Manage reusable schematic blocks")
    pb_sub = pb.add_subparsers(dest="blocks_cmd", required=True)
    pbl = pb_sub.add_parser("list", help="List saved blocks")
    pbl.add_argument("--json", action="store_true")
    pbl.set_defaults(func=cmd_blocks)
    pbs = pb_sub.add_parser("show", help="Show a saved block")
    pbs.add_argument("name")
    pbs.add_argument("--json", action="store_true",
                     help="Emit the raw block graph JSON")
    pbs.set_defaults(func=cmd_blocks)
    pbi = pb_sub.add_parser("import", help="Import a block JSON file")
    pbi.add_argument("path")
    pbi.add_argument("--name")
    pbi.set_defaults(func=cmd_blocks)
    pbe = pb_sub.add_parser("export", help="Export a saved block JSON file")
    pbe.add_argument("name")
    pbe.add_argument("path")
    pbe.set_defaults(func=cmd_blocks)

    pr = sub.add_parser("run", help="Run a .batsim project headlessly")
    pr.add_argument("project")
    pr.add_argument("--t-end", type=float, default=1.0)
    pr.add_argument("--dt", type=float, default=1e-3)
    pr.add_argument("--dc", action="store_true", help="DC operating point only")
    pr.add_argument("--csv", help="Write transient series to this CSV")
    pr.add_argument("--json", action="store_true",
                    help="Emit machine-readable summary JSON")
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

