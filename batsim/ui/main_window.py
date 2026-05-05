"""Main application window."""
from __future__ import annotations

import json
import os

from PyQt6.QtCore import Qt, QPointF, QTimer, QThread, QObject, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QPainter, QKeySequence, QShortcut, QClipboard
from PyQt6.QtWidgets import (QMainWindow, QGraphicsView, QDockWidget, QFileDialog,
                             QMessageBox, QToolBar, QApplication, QInputDialog)

from batsim.ui.canvas.scene import SchematicScene
from batsim.ui.canvas.component_item import ComponentItem
from batsim.ui.canvas.wire_item import WireItem
from batsim.ui.palette import PaletteWidget
from batsim.ui.inspector import InspectorWidget
from batsim.ui.outline import OutlineWidget
from batsim.ui.waveform_view import WaveformView
from batsim.ui.simulation_dialog import SimulationDialog
from batsim.ui.help_dialog import HelpDialog
from batsim.engine.netlist import from_graph, probe_map
from batsim.engine.nonlinear import solve_dc, solve_transient
from batsim.plugins.registry import make_battery
from batsim.plugins import refresh_if_changed
from batsim.io.project import save_project, load_project


CLIPBOARD_MIME = "application/x-batsim-graph"
BLOCKS_DIR = os.path.join(os.path.expanduser("~"), ".batsim", "blocks")


class _TransientWorker(QObject):
    """Runs ``solve_transient`` on a background QThread and emits live
    waveform chunks throttled by wall-clock time so the UI can redraw
    like an oscilloscope without freezing."""

    chunk = pyqtSignal(object, object, object, float)  # t, V, I, t_now
    finished = pyqtSignal(object)                      # final result dict
    failed = pyqtSignal(str)

    def __init__(self, netlist, t_end: float, dt: float,
                 throttle_ms: int = 80):
        super().__init__()
        self._netlist = netlist
        self._t_end = float(t_end)
        self._dt = float(dt)
        self._throttle = max(throttle_ms, 1) / 1000.0
        self._stop = False

    @pyqtSlot()
    def stop(self) -> None:
        self._stop = True

    @pyqtSlot()
    def run(self) -> None:
        import time as _time
        from batsim.engine.nonlinear import solve_transient as _st

        last_emit = [0.0]

        class _Stopped(Exception):
            pass

        def on_progress(k, n_steps, ts, V_hist, I_hist):
            if self._stop:
                raise _Stopped()
            now = _time.monotonic()
            is_last = (k >= n_steps)
            if not is_last and (now - last_emit[0]) < self._throttle:
                return
            last_emit[0] = now
            sl = slice(0, k + 1)
            t_part = ts[sl].copy()
            V_part = {n: a[sl].copy() for n, a in V_hist.items()}
            I_part = {n: a[sl].copy() for n, a in I_hist.items()}
            self.chunk.emit(t_part, V_part, I_part, float(ts[k]))

        try:
            res = _st(self._netlist, t_end=self._t_end, dt=self._dt,
                      on_progress=on_progress)
            self.finished.emit(res)
        except _Stopped:
            self.finished.emit({"t": [], "V": {}, "I": {}, "system": None,
                                "stopped": True})
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class SchematicView(QGraphicsView):
    def __init__(self, scene: SchematicScene):
        super().__init__(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setAcceptDrops(True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasFormat(PaletteWidget.MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):  # noqa: N802
        if e.mimeData().hasFormat(PaletteWidget.MIME):
            e.acceptProposedAction()

    def dropEvent(self, e):  # noqa: N802
        kind = bytes(e.mimeData().data(PaletteWidget.MIME)).decode("utf-8")
        pos = self.mapToScene(e.position().toPoint())
        self.scene().add_component(kind, pos)
        e.acceptProposedAction()

    def wheelEvent(self, e):  # noqa: N802
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
        else:
            super().wheelEvent(e)

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            from batsim.ui.canvas.wire_item import WireItem
            for it in list(self.scene().selectedItems()):
                if isinstance(it, ComponentItem):
                    self.scene().remove_component(it)
                elif isinstance(it, WireItem):
                    self.scene().remove_wire(it)
        elif e.key() == Qt.Key.Key_R:
            for it in self.scene().selectedItems():
                if isinstance(it, ComponentItem):
                    it.rotate_keeping_wires(90)
        elif e.key() == Qt.Key.Key_M:
            for it in self.scene().selectedItems():
                if isinstance(it, ComponentItem):
                    it.mirror_keeping_wires()
        elif e.key() == Qt.Key.Key_Escape:
            self.scene().cancel_wire()
        elif e.matches(QKeySequence.StandardKey.Copy):
            mw = self.window()
            if hasattr(mw, "copy_selection"):
                mw.copy_selection()
        elif e.matches(QKeySequence.StandardKey.Paste):
            mw = self.window()
            if hasattr(mw, "paste_clipboard"):
                mw.paste_clipboard(self.mapToScene(
                    self.viewport().rect().center()))
        elif (e.modifiers() & Qt.KeyboardModifier.ControlModifier and
              e.key() == Qt.Key.Key_G):
            mw = self.window()
            if hasattr(mw, "save_selection_as_block"):
                mw.save_selection_as_block()
        else:
            super().keyPressEvent(e)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BatSim — Battery & BMS Circuit Simulator")
        self.resize(1800, 1100)
        self._clipboard_graph: dict | None = None

        self.scene = SchematicScene(self)
        self.view = SchematicView(self.scene)
        self.setCentralWidget(self.view)

        # Undo / redo state — snapshot-based
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._suspend_undo: bool = False
        self._last_graph: dict = self._strip_runtime(self.scene.to_graph())
        self.scene.graphChanged.connect(self._on_graph_changed_for_undo)

        # Palette dock
        self.palette = PaletteWidget()
        d1 = QDockWidget("Components", self)
        d1.setWidget(self.palette)
        d1.setMinimumWidth(220)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, d1)

        # Inspector dock
        self.inspector = InspectorWidget()
        d2 = QDockWidget("Inspector", self)
        d2.setWidget(self.inspector)
        d2.setMinimumWidth(280)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, d2)

        # Outline dock (object browser) — listed below inspector on the right
        self.outline = OutlineWidget(self.scene)
        d_out = QDockWidget("Outline", self)
        d_out.setWidget(self.outline)
        d_out.setMinimumWidth(260)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, d_out)
        self.splitDockWidget(d2, d_out, Qt.Orientation.Vertical)

        # Waveform dock
        self.waveform = WaveformView()
        d3 = QDockWidget("Waveforms", self)
        d3.setWidget(self.waveform)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, d3)

        self.scene.selectionStateChanged.connect(self.inspector.set_component)

        self._build_toolbar()
        self._build_menu()
        self._help_dialog: HelpDialog | None = None
        # F1 = open manual (works regardless of focus)
        QShortcut(QKeySequence(Qt.Key.Key_F1), self,
                  activated=self.show_help)
        # Extra Ctrl+Shift+Z for redo (matches common conventions)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self,
                  activated=self.redo)
        self.statusBar().showMessage(
            "드래그로 부품 배치 → 핀에서 끌어 다른 핀에 놓아 연결 · R 회전 · M 좌우반전 · F1 매뉴얼")

    def _build_toolbar(self):
        tb = QToolBar("Main")
        self.addToolBar(tb)
        tb.addAction(self._act("New", self.new_project))
        tb.addAction(self._act("Open…", self.open_project))
        tb.addAction(self._act("Save…", self.save_project))
        tb.addSeparator()
        tb.addAction(self._act("Run", self.run_simulation, "Ctrl+R"))

    def _build_menu(self):
        m = self.menuBar().addMenu("&File")
        m.addAction(self._act("New", self.new_project, "Ctrl+N"))
        m.addAction(self._act("Open…", self.open_project, "Ctrl+O"))
        m.addAction(self._act("Save…", self.save_project, "Ctrl+S"))
        m.addSeparator()
        m.addAction(self._act("Quit", self.close, "Ctrl+Q"))
        em = self.menuBar().addMenu("&Edit")
        em.addAction(self._act("Undo", self.undo, "Ctrl+Z"))
        em.addAction(self._act("Redo", self.redo, "Ctrl+Y"))
        em.addSeparator()
        em.addAction(self._act("Copy", self.copy_selection, "Ctrl+C"))
        em.addAction(self._act("Paste", self.paste_clipboard, "Ctrl+V"))
        em.addSeparator()
        em.addAction(self._act("Save selection as block…",
                                self.save_selection_as_block, "Ctrl+G"))
        self._blocks_menu = em.addMenu("Insert block")
        self._refresh_blocks_menu()
        em.addSeparator()
        em.addAction(self._act("Open blocks folder", self.open_blocks_folder))
        sim = self.menuBar().addMenu("&Simulate")
        sim.addAction(self._act("Run…", self.run_simulation, "Ctrl+R"))
        sim.addSeparator()
        sim.addAction(self._act("Reload cell library", self.reload_cell_library, "F5"))
        helpm = self.menuBar().addMenu("&Help")
        helpm.addAction(self._act("Manual", self.show_help, "F1"))
        helpm.addAction(self._act("About", self.show_about))

        # Background polling so a freshly-added cell folder appears
        # without restart even if the user never opens the Simulate menu.
        self._cell_watch_timer = QTimer(self)
        self._cell_watch_timer.setInterval(5000)
        self._cell_watch_timer.timeout.connect(self._poll_cell_library)
        self._cell_watch_timer.start()

    def reload_cell_library(self):
        from batsim.plugins import discover, list_cells
        n = discover()
        msg = (f"Cell library reloaded — {len(list_cells())} cells "
               f"({n['cells']} entries from disk)")
        self.statusBar().showMessage(msg, 4000)
        if self.inspector is not None and self.inspector._comp is not None:
            self.inspector.set_component(self.inspector._comp)

    def _poll_cell_library(self):
        if refresh_if_changed():
            from batsim.plugins import list_cells
            self.statusBar().showMessage(
                f"셀 라이브러리 자동 갱신 — {len(list_cells())} cells", 3000)
            if self.inspector is not None and self.inspector._comp is not None:
                self.inspector.set_component(self.inspector._comp)

    def show_help(self):
        if self._help_dialog is None:
            self._help_dialog = HelpDialog(self)
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    def show_about(self):
        QMessageBox.about(
            self, "About BatSim",
            "<h3>BatSim</h3>"
            "<p>PSpice-style schematic editor + Python battery &amp; BMS engine.</p>"
            "<p>Press <b>F1</b> for the full manual.</p>")

    def _act(self, label, slot, shortcut=None):
        a = QAction(label, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        return a

    # --- undo / redo ---
    def _strip_runtime(self, graph: dict) -> dict:
        """Strip non-serialisable / volatile keys (cached waveforms, model
        instances) so snapshots compare cleanly."""
        import copy
        g = copy.deepcopy({"components": graph.get("components", []),
                           "wires": graph.get("wires", [])})
        for c in g["components"]:
            p = c.get("params", {}) or {}
            for k in ("_wf", "model"):
                p.pop(k, None)
        return g

    def _on_graph_changed_for_undo(self):
        if self._suspend_undo:
            return
        new = self._strip_runtime(self.scene.to_graph())
        if new == self._last_graph:
            return
        self._undo_stack.append(self._last_graph)
        if len(self._undo_stack) > 200:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._last_graph = new

    def _reset_undo_history(self):
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._last_graph = self._strip_runtime(self.scene.to_graph())

    def undo(self):
        if not self._undo_stack:
            self.statusBar().showMessage("취소할 작업이 없습니다 (Ctrl+Z)")
            return
        prev = self._undo_stack.pop()
        self._redo_stack.append(self._last_graph)
        self._suspend_undo = True
        try:
            self.scene.load_graph(prev)
        finally:
            self._suspend_undo = False
        self._last_graph = self._strip_runtime(self.scene.to_graph())
        self.statusBar().showMessage(
            f"되돌리기 (스택: {len(self._undo_stack)} undo / "
            f"{len(self._redo_stack)} redo)")

    def redo(self):
        if not self._redo_stack:
            self.statusBar().showMessage("재실행할 작업이 없습니다 (Ctrl+Y)")
            return
        nxt = self._redo_stack.pop()
        self._undo_stack.append(self._last_graph)
        self._suspend_undo = True
        try:
            self.scene.load_graph(nxt)
        finally:
            self._suspend_undo = False
        self._last_graph = self._strip_runtime(self.scene.to_graph())
        self.statusBar().showMessage(
            f"재실행 (스택: {len(self._undo_stack)} undo / "
            f"{len(self._redo_stack)} redo)")

    # --- file actions ---
    def new_project(self):
        self.scene.load_graph({"components": [], "wires": []})
        self._reset_undo_history()

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "",
                                              "BatSim project (*.batsim *.json)")
        if path:
            self.scene.load_graph(load_project(path))
            self._reset_undo_history()

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save project", "",
                                              "BatSim project (*.batsim)")
        if path:
            save_project(path, self.scene.to_graph())

    # --- simulation ---
    def run_simulation(self):
        # Disallow re-entry while another transient is streaming.
        if getattr(self, "_sim_thread", None) is not None:
            QMessageBox.information(self, "Simulation",
                                    "이미 시뮬레이션이 실행 중입니다.")
            return
        # Pass the current schematic so the dialog can compute t_end
        # from PCS cycle steps via the "Auto from PCS cycle" button.
        class _Bag:
            pass
        bag = _Bag()
        bag.components = self.scene.to_graph().get("components", [])
        dlg = SimulationDialog(self, netlist=bag)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        cfg = dlg.result_settings()
        graph = self.scene.to_graph()
        for c in graph["components"]:
            if c["kind"] == "BATTERY":
                p = c["params"]
                cell = p.get("cell") or None
                model_name = p.get("model")
                kwargs = {k: v for k, v in p.items() if k not in ("model", "cell")}
                c["model"] = make_battery(model_name=model_name, cell=cell, **kwargs)
        try:
            netlist = from_graph(graph)
        except Exception as exc:
            QMessageBox.critical(self, "Simulation error", str(exc))
            return

        if cfg["kind"] == "DC operating point":
            try:
                sys, x = solve_dc(netlist)
                volts = sys.node_voltages(x)
                msg = "\n".join(f"V({n}) = {v:.4f} V" for n, v in sorted(volts.items()))
                QMessageBox.information(self, "DC operating point", msg or "(empty)")
            except Exception as exc:
                QMessageBox.critical(self, "Simulation error", str(exc))
            return

        # --- Transient: stream waveforms live via worker thread ---
        aliases = probe_map(graph)
        self.waveform.begin_streaming(aliases, t_end=cfg["t_end"])

        thread = QThread(self)
        worker = _TransientWorker(netlist, t_end=cfg["t_end"], dt=cfg["dt"])
        worker.moveToThread(thread)
        self._sim_thread = thread
        self._sim_worker = worker
        self._sim_t_end = float(cfg["t_end"])
        self._sim_aliases = aliases

        thread.started.connect(worker.run)
        worker.chunk.connect(self._on_sim_chunk)
        worker.finished.connect(self._on_sim_finished)
        worker.failed.connect(self._on_sim_failed)
        try:
            self.waveform.stopRequested.disconnect()
        except TypeError:
            pass
        self.waveform.stopRequested.connect(worker.stop)

        self.statusBar().showMessage(
            f"Transient running… t_end={cfg['t_end']} s · dt={cfg['dt']} s")
        thread.start()

    @pyqtSlot(object, object, object, float)
    def _on_sim_chunk(self, t_part, V_part, I_part, t_now):
        self.waveform.push_chunk(t_part, V_part, I_part)
        if self._sim_t_end > 0:
            pct = min(100, int(100.0 * t_now / self._sim_t_end))
        else:
            pct = 0
        self.statusBar().showMessage(
            f"Transient running… t={t_now:.3f}s / {self._sim_t_end:g}s ({pct}%)")

    @pyqtSlot(object)
    def _on_sim_finished(self, result):
        self.waveform.end_streaming(result)
        self._teardown_sim_thread()
        n_steps = len(result.get("t", []) or [])
        if result.get("stopped"):
            self.statusBar().showMessage("Transient stopped by user.")
        else:
            npr = (len(self._sim_aliases.get("voltages", {})) +
                   len(self._sim_aliases.get("currents", {})))
            self.statusBar().showMessage(
                f"Transient done: {n_steps} steps over {self._sim_t_end:g} s · "
                f"{npr} probe(s) found")

    @pyqtSlot(str)
    def _on_sim_failed(self, msg):
        self.waveform.end_streaming(None)
        self._teardown_sim_thread()
        self.statusBar().showMessage("Transient failed.")
        QMessageBox.critical(self, "Simulation error", msg)

    def _teardown_sim_thread(self):
        thread = getattr(self, "_sim_thread", None)
        worker = getattr(self, "_sim_worker", None)
        if thread is not None:
            thread.quit()
            thread.wait(2000)
            thread.deleteLater()
        if worker is not None:
            worker.deleteLater()
        self._sim_thread = None
        self._sim_worker = None
        self._sim_aliases = None
        try:
            self.waveform.stopRequested.disconnect()
        except TypeError:
            pass

    # --- copy / paste / blocks ---
    def _selection_subgraph(self) -> dict | None:
        sel_comps = [it for it in self.scene.selectedItems()
                     if isinstance(it, ComponentItem)]
        if not sel_comps:
            return None
        ids = {c.cid for c in sel_comps}
        comps = []
        for c in sel_comps:
            comps.append({
                "id": c.cid,
                "kind": c.kind,
                "params": dict(c.params),
                "pos": [c.pos().x(), c.pos().y()],
                "rotation": c.rotation(),
                "tap_pin": c.tap_pin,
            })
        wires = []
        for w in self.scene._wires:
            if w.a_comp.cid in ids and w.b_comp.cid in ids:
                wires.append({"a": f"{w.a_comp.cid}.{w.a_pin}",
                              "b": f"{w.b_comp.cid}.{w.b_pin}"})
        return {"components": comps, "wires": wires}

    def _paste_subgraph(self, sub: dict, anchor: QPointF | None = None) -> None:
        if not sub or not sub.get("components"):
            return
        # Compute offset
        comps = sub["components"]
        xs = [c["pos"][0] for c in comps]
        ys = [c["pos"][1] for c in comps]
        if anchor is not None:
            cx = (min(xs) + max(xs)) / 2.0
            cy = (min(ys) + max(ys)) / 2.0
            ox, oy = anchor.x() - cx, anchor.y() - cy
        else:
            ox, oy = 20.0, 20.0
        # Re-id
        from batsim.ui.canvas.scene import CATALOG
        from batsim.ui.canvas.wire_item import WireItem
        id_map: dict[str, ComponentItem] = {}
        new_items: list[ComponentItem] = []
        self.scene.clearSelection()
        for c in comps:
            kind = c["kind"]
            new_id = self.scene.next_id(kind)
            spec = CATALOG[kind]
            item = ComponentItem(new_id, kind, spec)
            item.params = dict(c.get("params", spec["default_params"]))
            item.setPos(QPointF(c["pos"][0] + ox, c["pos"][1] + oy))
            item.setRotation(c.get("rotation", 0))
            self.scene.addItem(item)
            self.scene._components.append(item)
            id_map[c["id"]] = item
            item.setSelected(True)
            new_items.append(item)
        for w in sub.get("wires", []):
            a_id, a_pin = w["a"].split(".")
            b_id, b_pin = w["b"].split(".")
            if a_id not in id_map or b_id not in id_map:
                continue
            wire = WireItem(id_map[a_id], int(a_pin),
                            id_map[b_id], int(b_pin))
            self.scene.addItem(wire)
            self.scene._wires.append(wire)
        self.scene.graphChanged.emit()
        self.statusBar().showMessage(
            f"붙여넣기: {len(new_items)}개 부품, {len(sub.get('wires', []))}개 와이어")

    def copy_selection(self):
        sub = self._selection_subgraph()
        if not sub:
            self.statusBar().showMessage("선택된 부품이 없습니다")
            return
        self._clipboard_graph = sub
        # Mirror to system clipboard as JSON text for cross-instance paste
        try:
            QApplication.clipboard().setText(
                "BATSIM:" + json.dumps(sub, ensure_ascii=False))
        except Exception:
            pass
        self.statusBar().showMessage(
            f"복사: {len(sub['components'])}개 부품, {len(sub['wires'])}개 와이어")

    def paste_clipboard(self, anchor: QPointF | None = None):
        if isinstance(anchor, bool) or anchor is False or anchor is True:
            anchor = None  # action triggers pass a bool
        sub = self._clipboard_graph
        if sub is None:
            try:
                txt = QApplication.clipboard().text()
                if txt.startswith("BATSIM:"):
                    sub = json.loads(txt[len("BATSIM:"):])
            except Exception:
                sub = None
        if not sub:
            self.statusBar().showMessage("클립보드가 비어있습니다")
            return
        self._paste_subgraph(sub, anchor)

    def save_selection_as_block(self):
        sub = self._selection_subgraph()
        if not sub:
            QMessageBox.information(self, "Save block",
                                    "먼저 블록으로 묶을 부품을 선택하세요.")
            return
        name, ok = QInputDialog.getText(self, "Save block",
                                        "블록 이름:")
        if not ok or not name.strip():
            return
        os.makedirs(BLOCKS_DIR, exist_ok=True)
        safe = "".join(ch for ch in name.strip()
                       if ch.isalnum() or ch in ("-", "_", " ")).strip()
        if not safe:
            return
        path = os.path.join(BLOCKS_DIR, safe + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sub, f, ensure_ascii=False, indent=2)
        self._refresh_blocks_menu()
        self.statusBar().showMessage(f"블록 저장: {path}")

    def _refresh_blocks_menu(self):
        if not hasattr(self, "_blocks_menu"):
            return
        self._blocks_menu.clear()
        os.makedirs(BLOCKS_DIR, exist_ok=True)
        files = sorted(f for f in os.listdir(BLOCKS_DIR) if f.endswith(".json"))
        if not files:
            a = self._blocks_menu.addAction("(저장된 블록 없음)")
            a.setEnabled(False)
            return
        for fn in files:
            name = os.path.splitext(fn)[0]
            path = os.path.join(BLOCKS_DIR, fn)
            act = QAction(name, self)
            act.triggered.connect(lambda _=False, p=path: self._insert_block(p))
            self._blocks_menu.addAction(act)

    def _insert_block(self, path: str):
        try:
            with open(path, encoding="utf-8") as f:
                sub = json.load(f)
        except Exception as exc:
            QMessageBox.critical(self, "Insert block", str(exc))
            return
        center = self.view.mapToScene(self.view.viewport().rect().center())
        self._paste_subgraph(sub, center)

    def open_blocks_folder(self):
        os.makedirs(BLOCKS_DIR, exist_ok=True)
        try:
            os.startfile(BLOCKS_DIR)  # type: ignore[attr-defined]
        except Exception:
            QMessageBox.information(self, "Blocks folder", BLOCKS_DIR)
