"""Reusable schematic block storage.

Blocks are plain JSON subgraphs stored under ``~/.batsim/blocks`` so the
GUI and CLI can share the same module library.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


BLOCKS_DIR = Path(os.path.expanduser("~")) / ".batsim" / "blocks"


def safe_block_name(name: str) -> str:
    safe = "".join(ch for ch in name.strip()
                   if ch.isalnum() or ch in ("-", "_", " ")).strip()
    if not safe:
        raise ValueError("empty block name")
    return safe


def block_path(name: str) -> Path:
    return BLOCKS_DIR / (safe_block_name(name) + ".json")


def list_blocks() -> list[str]:
    BLOCKS_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(p.stem for p in BLOCKS_DIR.glob("*.json"))


def load_block(name: str) -> dict:
    return json.loads(block_path(name).read_text(encoding="utf-8"))


def save_block(name: str, graph: dict) -> Path:
    BLOCKS_DIR.mkdir(parents=True, exist_ok=True)
    path = block_path(name)
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def import_block(path: str | Path, name: str | None = None) -> Path:
    src = Path(path)
    graph = json.loads(src.read_text(encoding="utf-8"))
    return save_block(name or src.stem, graph)


def export_block(name: str, path: str | Path) -> Path:
    dst = Path(path)
    graph = load_block(name)
    dst.write_text(json.dumps(graph, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    return dst


