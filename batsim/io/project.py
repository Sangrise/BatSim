"""Project file I/O (.batsim is plain JSON)."""
from __future__ import annotations

import json
from pathlib import Path


def save_project(path: str | Path, graph: dict) -> None:
    Path(path).write_text(json.dumps(graph, indent=2), encoding="utf-8")


def load_project(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
