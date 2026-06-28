"""Plugin discovery: scans Python and data-file extensions on startup."""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import os
import sys
from pathlib import Path

from .registry import CELL_LIBRARY, BMS_LIBRARY

try:
    import yaml  # optional
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


REPO_ROOT = Path(__file__).resolve().parents[2]


# Top-level keys recognised in meta.csv (everything else goes under "params")
_META_TOP_KEYS = {"name", "model", "manufacturer", "chemistry"}


def _load_data_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        if not _HAS_YAML:
            raise RuntimeError(f"PyYAML required to load {path}")
        return yaml.safe_load(text)
    return json.loads(text)


def _coerce_scalar(s: str):
    s = s.strip()
    if s == "":
        return None
    try:
        return int(s) if s.lstrip("-").isdigit() else float(s)
    except ValueError:
        low = s.lower()
        if low == "true":  return True
        if low == "false": return False
        return s


def _read_csv(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.reader(f)
                if row and any(c.strip() for c in row)
                and not row[0].lstrip().startswith("#")]


def _load_csv_cell_dir(folder: Path) -> dict:
    """Assemble a cell dict from a folder of CSV files.

    Recognised files (all optional except meta.csv):
        meta.csv       — key,value rows (name, model, chemistry, capacity_Ah,
                         R0, soc0, ...).  Known top-level keys go to the root
                         of the dict; the rest are merged under ``params``.
        ocv.csv        — header ``soc,V_oc`` → params["ocv_table"] = [[s,v]..]
        ocv_chg.csv    — same → params["ocv_table_chg"]
        ocv_dch.csv    — same → params["ocv_table_dch"]
        rc_pairs.csv   — header ``R,C``     → params["RC_pairs"] = [[R,C]..]

    Any other ``*.csv`` is preserved verbatim (parsed as a list of rows of
    coerced scalars) under ``params["_extra"][<stem>]`` so future data files
    survive without code changes.
    """
    out: dict = {"params": {}}
    params = out["params"]

    # meta
    meta_path = folder / "meta.csv"
    if meta_path.exists():
        rows = _read_csv(meta_path)
        # Optional header row "key,value"
        if rows and [c.strip().lower() for c in rows[0]] == ["key", "value"]:
            rows = rows[1:]
        for row in rows:
            if len(row) < 2: continue
            k = row[0].strip()
            v = _coerce_scalar(row[1])
            if not k: continue
            if k in _META_TOP_KEYS:
                out[k] = v
            else:
                params[k] = v

    def _table_from(path: Path, *, ncols: int = 2):
        rows = _read_csv(path)
        # Skip header if first row is non-numeric.
        if rows and not all(_is_number(c) for c in rows[0][:ncols]):
            rows = rows[1:]
        return [[float(c) for c in r[:ncols]] for r in rows
                if len(r) >= ncols and all(_is_number(c) for c in r[:ncols])]

    if (folder / "ocv.csv").exists():
        params["ocv_table"] = _table_from(folder / "ocv.csv")
    if (folder / "ocv_chg.csv").exists():
        params["ocv_table_chg"] = _table_from(folder / "ocv_chg.csv")
    if (folder / "ocv_dch.csv").exists():
        params["ocv_table_dch"] = _table_from(folder / "ocv_dch.csv")
    if (folder / "rc_pairs.csv").exists():
        params["RC_pairs"] = _table_from(folder / "rc_pairs.csv")

    # Forward-compat: stash any other CSV (key,value or table) under _extra.
    known = {"meta.csv", "ocv.csv", "ocv_chg.csv", "ocv_dch.csv",
             "rc_pairs.csv"}
    extras: dict = {}
    for f in sorted(folder.glob("*.csv")):
        if f.name in known: continue
        extras[f.stem] = [[_coerce_scalar(c) for c in r]
                          for r in _read_csv(f)]
    if extras:
        params["_extra"] = extras

    out.setdefault("name", folder.name)
    return out


def _is_number(s) -> bool:
    if s is None: return False
    try:
        float(str(s).strip()); return True
    except ValueError:
        return False


def _import_module_from_path(path: Path) -> None:
    mod_name = f"_batsim_plugin_{path.stem}_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)


def _python_plugin_dirs() -> list[Path]:
    dirs: list[Path] = [
        Path(__file__).parent / "builtin",
        Path.home() / ".batsim" / "plugins",
    ]
    env = os.environ.get("BATSIM_PLUGIN_PATH", "")
    for p in env.split(os.pathsep):
        if p.strip():
            dirs.append(Path(p))
    return [d for d in dirs if d.exists()]


def _data_dirs() -> dict[str, list[Path]]:
    base = REPO_ROOT / "data"
    user = Path.home() / ".batsim" / "data"
    out = {"cells": [], "bms": []}
    for root in (base, user):
        for sub in ("cells", "bms"):
            d = root / sub
            if d.exists():
                out[sub].append(d)
    return out


def _scan_signature() -> tuple:
    """Cheap fingerprint of every cell/bms file's mtime + size.

    Used by ``refresh_if_changed()`` to skip work when nothing on disk
    has changed since the last scan.  Walks one level into subfolders
    so CSV-folder cells are picked up too.
    """
    sig: list = []
    for d in _data_dirs()["cells"] + _data_dirs()["bms"]:
        for p in sorted(d.rglob("*")):
            if p.is_file():
                try:
                    st = p.stat()
                    sig.append((str(p), st.st_mtime_ns, st.st_size))
                except OSError:
                    pass
    return tuple(sig)


_LAST_SIG: tuple | None = None
_DISCOVERED_ONCE = False


def discover(*, prune: bool = True) -> dict[str, int]:
    """(Re)scan all plugin sources.  Returns counts.

    With ``prune=True`` (default) the cell / BMS libraries are cleared
    first so deletions on disk are reflected.  Python plugins are only
    imported on the *first* call — re-importing them every refresh would
    duplicate ``register_battery`` calls.
    """
    global _LAST_SIG, _DISCOVERED_ONCE
    counts = {"python": 0, "cells": 0, "bms": 0}

    # 1) Python plugins — load once per process.
    if not _DISCOVERED_ONCE:
        for d in _python_plugin_dirs():
            for f in sorted(d.glob("*.py")):
                if f.name.startswith("_"):
                    continue
                _import_module_from_path(f)
                counts["python"] += 1
        _DISCOVERED_ONCE = True

    # 2) Data plugins — re-scan every call.
    if prune:
        CELL_LIBRARY.clear()
        BMS_LIBRARY.clear()

    dirs = _data_dirs()
    for d in dirs["cells"]:
        for f in sorted(list(d.glob("*.json")) + list(d.glob("*.yaml"))
                       + list(d.glob("*.yml"))):
            data = _load_data_file(f)
            name = data.get("name", f.stem)
            CELL_LIBRARY[name] = data
            counts["cells"] += 1
        for sub in sorted(p for p in d.iterdir() if p.is_dir()):
            if not (sub / "meta.csv").exists():
                continue
            data = _load_csv_cell_dir(sub)
            name = data.get("name", sub.name)
            CELL_LIBRARY[name] = data
            counts["cells"] += 1
    for d in dirs["bms"]:
        for f in sorted(list(d.glob("*.json")) + list(d.glob("*.yaml"))
                       + list(d.glob("*.yml"))):
            data = _load_data_file(f)
            name = data.get("name", f.stem)
            BMS_LIBRARY[name] = data
            counts["bms"] += 1

    _LAST_SIG = _scan_signature()
    return counts


def refresh_if_changed() -> bool:
    """Cheap re-scan triggered from the UI.

    Returns True if the data directory changed and the libraries were
    reloaded, False if nothing changed.
    """
    sig = _scan_signature()
    if sig == _LAST_SIG and _DISCOVERED_ONCE:
        return False
    discover()
    return True
