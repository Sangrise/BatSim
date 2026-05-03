"""Render PNG screenshots used by the HTML manual.

Usage:  python scripts/make_manual_screens.py
Output: resources/help/img/*.png
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, QRectF, QSize
from PyQt6.QtGui import QImage, QPainter, QColor
from PyQt6.QtWidgets import QApplication

from batsim.ui.canvas.scene import SchematicScene
from batsim.ui.canvas.wire_item import WireItem


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "resources", "help", "img")
os.makedirs(OUT, exist_ok=True)


def render_scene(scene: SchematicScene, name: str,
                 padding: int = 40, scale: float = 1.5) -> str:
    for w in scene._wires:
        w.refresh()
    if hasattr(scene, "_crossings") and scene._crossings is not None:
        scene._crossings.recompute()
    rect: QRectF = scene.itemsBoundingRect().adjusted(-padding, -padding,
                                                       padding, padding)
    size = QSize(max(int(rect.width() * scale), 200),
                 max(int(rect.height() * scale), 150))
    img = QImage(size, QImage.Format.Format_ARGB32)
    img.fill(QColor("#1e1e1e"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    scene.render(p, target=QRectF(0, 0, size.width(), size.height()),
                 source=rect)
    p.end()
    path = os.path.join(OUT, name + ".png")
    img.save(path)
    print(f"  wrote {os.path.relpath(path, HERE)}  "
          f"({size.width()}x{size.height()})")
    return path


def _wire(sc, a, ai, b, bi):
    w = WireItem(a, ai, b, bi)
    sc.addItem(w); sc._wires.append(w)
    return w


def shot_simple_rc():
    sc = SchematicScene()
    v = sc.add_component("V", QPointF(-160, 0))
    r = sc.add_component("R", QPointF(0, 0))
    c = sc.add_component("C", QPointF(160, 0))
    g = sc.add_component("GND", QPointF(0, 100))
    _wire(sc, v, 1, r, 0)
    _wire(sc, r, 1, c, 0)
    _wire(sc, c, 1, g, 0)
    _wire(sc, v, 0, g, 0)
    return render_scene(sc, "schematic_rc")


def shot_parallel():
    sc = SchematicScene()
    v = sc.add_component("V", QPointF(-220, 0))
    r1 = sc.add_component("R", QPointF(-60, 0))
    r2 = sc.add_component("R", QPointF(120, -60))
    c1 = sc.add_component("C", QPointF(120, 60))
    g = sc.add_component("GND", QPointF(220, 100))
    _wire(sc, v, 1, r1, 0)
    _wire(sc, r1, 1, r2, 0)
    _wire(sc, r1, 1, c1, 0)
    _wire(sc, r2, 1, g, 0)
    _wire(sc, c1, 1, g, 0)
    _wire(sc, v, 0, g, 0)
    return render_scene(sc, "schematic_parallel")


def shot_battery_load():
    sc = SchematicScene()
    b = sc.add_component("BATTERY", QPointF(-160, 0))
    r = sc.add_component("R", QPointF(40, 0))
    pr = sc.add_component("PROBE", QPointF(40, -80))
    g = sc.add_component("GND", QPointF(40, 120))
    _wire(sc, b, 1, r, 0)
    _wire(sc, r, 1, g, 0)
    _wire(sc, b, 0, g, 0)
    _wire(sc, pr, 0, r, 0)
    return render_scene(sc, "schematic_battery_load")


def shot_tap_junction():
    sc = SchematicScene()
    r1 = sc.add_component("R", QPointF(-180, 0))
    r2 = sc.add_component("R", QPointF(180, 0))
    r3 = sc.add_component("R", QPointF(0, 140))
    _wire(sc, r1, 1, r2, 0)
    j = sc.add_component("JUNCTION", QPointF(0, 0))
    j.tap_pin = f"{r1.cid}.1"
    j.tap_wire = sc._wires[0]
    j.setPos(QPointF(0, 0))
    _wire(sc, r3, 0, j, 0)
    return render_scene(sc, "schematic_tap")


def shot_main_window(app):
    from batsim.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1500, 900)
    sc = w.scene
    v = sc.add_component("V", QPointF(-200, 0))
    r1 = sc.add_component("R", QPointF(-40, 0))
    r2 = sc.add_component("R", QPointF(140, -60))
    c1 = sc.add_component("C", QPointF(140, 60))
    g = sc.add_component("GND", QPointF(240, 100))
    _wire(sc, v, 1, r1, 0)
    _wire(sc, r1, 1, r2, 0); _wire(sc, r1, 1, c1, 0)
    _wire(sc, r2, 1, g, 0); _wire(sc, c1, 1, g, 0); _wire(sc, v, 0, g, 0)
    w.show()
    app.processEvents()
    pix = w.grab()
    path = os.path.join(OUT, "main_window.png")
    pix.save(path, "PNG")
    print(f"  wrote {os.path.relpath(path, HERE)}  "
          f"({pix.width()}x{pix.height()})")
    w.close()


def shot_inspector_focus(app):
    from batsim.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1500, 900)
    b = w.scene.add_component("BATTERY", QPointF(0, 0))
    b.setSelected(True)
    w.scene.selectionStateChanged.emit(b)
    w.show()
    app.processEvents()
    pix = w.grab()
    crop = pix.copy(pix.width() - 360, 60, 360, 460)
    path = os.path.join(OUT, "inspector_battery.png")
    crop.save(path, "PNG")
    print(f"  wrote {os.path.relpath(path, HERE)}  "
          f"({crop.width()}x{crop.height()})")
    w.close()


def shot_palette(app):
    from batsim.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1500, 900)
    w.show()
    app.processEvents()
    pix = w.grab()
    crop = pix.copy(0, 60, 240, 600)
    path = os.path.join(OUT, "palette.png")
    crop.save(path, "PNG")
    print(f"  wrote {os.path.relpath(path, HERE)}  "
          f"({crop.width()}x{crop.height()})")
    w.close()


def shot_waveform(app):
    """Run a quick transient and capture the waveform dock."""
    from batsim.ui.main_window import MainWindow
    from batsim.engine.netlist import from_graph, probe_map
    from batsim.engine.nonlinear import solve_transient
    w = MainWindow()
    w.resize(1500, 900)
    sc = w.scene
    v = sc.add_component("V", QPointF(-160, 0))
    r = sc.add_component("R", QPointF(0, 0))
    c = sc.add_component("C", QPointF(160, 0))
    pr = sc.add_component("PROBE", QPointF(80, -80))
    g = sc.add_component("GND", QPointF(0, 120))
    _wire(sc, v, 1, r, 0); _wire(sc, r, 1, c, 0); _wire(sc, c, 1, g, 0)
    _wire(sc, v, 0, g, 0); _wire(sc, pr, 0, r, 1)
    g_dict = sc.to_graph()
    nl = from_graph(g_dict)
    res = solve_transient(nl, t_end=0.05, dt=0.0005)
    w.waveform.show_results(res, aliases=probe_map(g_dict))
    w.show()
    app.processEvents()
    pix = w.grab()
    crop = pix.copy(0, pix.height() - 320, pix.width(), 320)
    path = os.path.join(OUT, "waveform.png")
    crop.save(path, "PNG")
    print(f"  wrote {os.path.relpath(path, HERE)}  "
          f"({crop.width()}x{crop.height()})")
    w.close()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    print("Rendering manual screenshots …")
    shot_simple_rc()
    shot_parallel()
    shot_battery_load()
    shot_tap_junction()
    shot_main_window(app)
    shot_inspector_focus(app)
    shot_palette(app)
    shot_waveform(app)
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
