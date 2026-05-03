"""Plugin discovery: scans Python and data-file extensions on startup."""
from __future__ import annotations

import importlib.util
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


def _load_data_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        if not _HAS_YAML:
            raise RuntimeError(f"PyYAML required to load {path}")
        return yaml.safe_load(text)
    return json.loads(text)


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


def discover() -> dict[str, int]:
    """Scan all plugin sources. Returns counts."""
    counts = {"python": 0, "cells": 0, "bms": 0}

    # 1) Python plugins
    for d in _python_plugin_dirs():
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_"):
                continue
            _import_module_from_path(f)
            counts["python"] += 1

    # 2) Data plugins
    dirs = _data_dirs()
    for d in dirs["cells"]:
        for f in sorted(list(d.glob("*.json")) + list(d.glob("*.yaml"))
                       + list(d.glob("*.yml"))):
            data = _load_data_file(f)
            name = data.get("name", f.stem)
            CELL_LIBRARY[name] = data
            counts["cells"] += 1
    for d in dirs["bms"]:
        for f in sorted(list(d.glob("*.json")) + list(d.glob("*.yaml"))
                       + list(d.glob("*.yml"))):
            data = _load_data_file(f)
            name = data.get("name", f.stem)
            BMS_LIBRARY[name] = data
            counts["bms"] += 1

    return counts
