"""Multi-pane waveform viewer with optional dual Y-axes per panel.

Each panel has a 3-state list of signals: off / Left axis / Right axis.
Click a row to cycle: Off → Left → Right → Off.  The plot keeps a primary
ViewBox and a secondary right-axis ViewBox, kept in sync via Qt signals.

`show_results(...)` is called after every simulation; on the very first
result (single default panel still pristine) the viewer auto-splits into
two panels — one for V signals (Left=V, Right=any extra V), one for I.
"""
from __future__ import annotations

from typing import Iterable

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
                             QPushButton, QListWidget, QListWidgetItem,
                             QLabel, QFrame)


COLORS_L = ["#ff7f50", "#ffd700", "#ee82ee", "#ffa07a"]
COLORS_R = ["#7fffd4", "#87cefa", "#90ee90", "#add8e6"]


pg.setConfigOptions(antialias=True, background="#181818", foreground="#dcdcdc")


# Per-row axis assignment: 0 = off, 1 = left, 2 = right.
AXIS_OFF, AXIS_LEFT, AXIS_RIGHT = 0, 1, 2
AXIS_LABEL = {AXIS_OFF: "  · ", AXIS_LEFT: " L  ", AXIS_RIGHT: " R  "}


class _PlotPanel(QFrame):
    """One row: a signal selector on the left, a dual-axis plot on the right."""

    def __init__(self, parent: "WaveformView", index: int):
        super().__init__()
        self._owner = parent
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._axis: dict[str, int] = {}  # signal name -> AXIS_*

        root = QHBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)

        side = QVBoxLayout()
        self.title = QLabel(f"Plot {index + 1}")
        self.title.setStyleSheet("color:#9cd8ff; font-weight:bold;")
        side.addWidget(self.title)

        hint = QLabel("클릭: Off → L → R")
        hint.setStyleSheet("color:#888; font-size:10px;")
        side.addWidget(hint)

        self.list = QListWidget()
        self.list.itemClicked.connect(self._cycle_axis)
        side.addWidget(self.list, 1)

        btns = QHBoxLayout()
        b_all = QPushButton("All→L")
        b_all.clicked.connect(lambda: self._set_all(AXIS_LEFT))
        b_none = QPushButton("None")
        b_none.clicked.connect(lambda: self._set_all(AXIS_OFF))
        b_remove = QPushButton("× Remove")
        b_remove.clicked.connect(lambda: self._owner.remove_panel(self))
        btns.addWidget(b_all); btns.addWidget(b_none); btns.addWidget(b_remove)
        side.addLayout(btns)

        side_w = QWidget()
        side_w.setLayout(side)
        side_w.setFixedWidth(220)
        root.addWidget(side_w)

        # --- Plot with primary + secondary ViewBox ---
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.setLabel("bottom", "t", units="s")
        self.plot.addLegend()

        self._right_vb = pg.ViewBox()
        self.plot.scene().addItem(self._right_vb)
        self.plot.showAxis("right")
        self.plot.getAxis("right").linkToView(self._right_vb)
        self._right_vb.setXLink(self.plot.getViewBox())
        self.plot.getAxis("right").setLabel("")
        self.plot.getViewBox().sigResized.connect(self._sync_right_vb)

        root.addWidget(self.plot, 1)

    # --- ViewBox sync ---
    def _sync_right_vb(self) -> None:
        self._right_vb.setGeometry(self.plot.getViewBox().sceneBoundingRect())
        self._right_vb.linkedViewChanged(self.plot.getViewBox(),
                                         self._right_vb.XAxis)

    # --- API ---
    def set_available_signals(self, signals: list[str],
                              default_axis: dict[str, int] | None = None,
                              keep_existing: bool = True) -> None:
        """Rebuild the row list, preserving prior axis assignments where the
        signal still exists. ``default_axis`` overrides for new signals.
        """
        prior = dict(self._axis) if keep_existing else {}
        self.list.blockSignals(True)
        self.list.clear()
        self._axis.clear()
        for s in signals:
            ax = prior.get(s,
                           (default_axis or {}).get(s, AXIS_OFF))
            self._axis[s] = ax
            it = QListWidgetItem(self._row_label(s, ax))
            it.setData(Qt.ItemDataRole.UserRole, s)
            self.list.addItem(it)
        self.list.blockSignals(False)
        self._refresh_plot()

    def axis_state(self) -> dict[str, int]:
        return dict(self._axis)

    def _row_label(self, name: str, ax: int) -> str:
        return f"{AXIS_LABEL[ax]} {name}"

    def _cycle_axis(self, item: QListWidgetItem) -> None:
        s = item.data(Qt.ItemDataRole.UserRole)
        ax = (self._axis.get(s, AXIS_OFF) + 1) % 3
        self._axis[s] = ax
        item.setText(self._row_label(s, ax))
        self._refresh_plot()

    def _set_all(self, ax: int) -> None:
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            it = self.list.item(i)
            s = it.data(Qt.ItemDataRole.UserRole)
            self._axis[s] = ax
            it.setText(self._row_label(s, ax))
        self.list.blockSignals(False)
        self._refresh_plot()

    def _refresh_plot(self, *_) -> None:
        # Clear existing curves + right viewbox
        self.plot.clear()
        for it in list(self._right_vb.allChildren()):
            self._right_vb.removeItem(it)
        # Rebuild legend (PlotWidget.clear() detaches legend items)
        try:
            leg = self.plot.plotItem.legend
            if leg is not None:
                leg.clear()
        except Exception:
            pass
        data = self._owner._signal_data
        t = self._owner._t
        if t is None:
            return
        l_idx = r_idx = 0
        l_label = r_label = None
        for s, ax in self._axis.items():
            arr = data.get(s)
            if arr is None or ax == AXIS_OFF:
                continue
            if ax == AXIS_LEFT:
                color = COLORS_L[l_idx % len(COLORS_L)]
                pen = pg.mkPen(color, width=2)
                self.plot.plot(t, arr, pen=pen, name=s)
                l_idx += 1
                if l_label is None:
                    l_label = s
            else:  # AXIS_RIGHT
                color = COLORS_R[r_idx % len(COLORS_R)]
                pen = pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine)
                curve = pg.PlotCurveItem(t, arr, pen=pen, name=s)
                self._right_vb.addItem(curve)
                # Add a phantom legend entry on the main plot so the user
                # sees the right-axis traces too.
                try:
                    self.plot.plotItem.legend.addItem(curve, f"{s}  (R)")
                except Exception:
                    pass
                r_idx += 1
                if r_label is None:
                    r_label = s
        # Axis labels — use units from the first signal for hint
        self.plot.setLabel("left", _kind_label(l_label) if l_label else "")
        self.plot.getAxis("right").setLabel(
            _kind_label(r_label) if r_label else "")
        self._sync_right_vb()


def _kind_label(name: str | None) -> str:
    if not name:
        return ""
    if name.startswith("V("):
        return "Voltage [V]"
    if name.startswith("I("):
        return "Current [A]"
    return name


class WaveformView(QWidget):
    """Backwards-compatible name; now hosts multiple panels with dual axes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        bar = QHBoxLayout()
        b_add = QPushButton("+ Add plot")
        b_add.clicked.connect(self.add_panel)
        b_split = QPushButton("Split V / I")
        b_split.clicked.connect(self._split_v_i)
        bar.addWidget(b_add)
        bar.addWidget(b_split)
        bar.addStretch(1)
        self._info = QLabel("No data — run a simulation (Ctrl+R)")
        self._info.setStyleSheet("color:#888;")
        bar.addWidget(self._info)
        layout.addLayout(bar)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(self.splitter, 1)

        self._panels: list[_PlotPanel] = []
        self._t = None
        self._signal_data: dict[str, list[float]] = {}
        self._available: list[str] = []
        self._user_customised = False  # tracks any post-result panel changes

        self.add_panel()  # start with one

    # --- panel management ---
    def add_panel(self) -> _PlotPanel:
        idx = len(self._panels)
        panel = _PlotPanel(self, idx)
        self._panels.append(panel)
        self.splitter.addWidget(panel)
        panel.set_available_signals(self._available)
        return panel

    def remove_panel(self, panel: _PlotPanel) -> None:
        if len(self._panels) <= 1:
            return
        if panel in self._panels:
            self._panels.remove(panel)
        panel.setParent(None)
        panel.deleteLater()
        for i, p in enumerate(self._panels):
            p.title.setText(f"Plot {i + 1}")

    # --- explicit V/I split ---
    def _split_v_i(self) -> None:
        """Drop all panels and create one V panel + one I panel."""
        while len(self._panels) > 0:
            p = self._panels.pop()
            p.setParent(None)
            p.deleteLater()
        v_panel = self.add_panel()
        i_panel = self.add_panel()
        v_panel.title.setText("Voltage")
        i_panel.title.setText("Current")
        v_axis = {s: AXIS_LEFT for s in self._available
                  if s.startswith("V(")}
        i_axis = {s: AXIS_LEFT for s in self._available
                  if s.startswith("I(")}
        v_panel.set_available_signals(self._available,
                                      default_axis=v_axis,
                                      keep_existing=False)
        i_panel.set_available_signals(self._available,
                                      default_axis=i_axis,
                                      keep_existing=False)

    # --- data ingest ---
    def show_results(self, result: dict,
                     aliases: dict | None = None,
                     signals: Iterable[str] | None = None) -> None:
        """Push a fresh simulation result into every panel.

        On the very first run (still the default single empty panel) we
        automatically split into two panels — voltages on the first,
        currents on the second.
        """
        self._t = result["t"]
        V = result.get("V", {})
        I = result.get("I", {})
        aliases = aliases or {"voltages": {}, "currents": {}}

        data: dict[str, list[float]] = {}
        for pid, info in aliases.get("voltages", {}).items():
            if isinstance(info, tuple):
                npos, nneg = info
                arr_p = V.get(npos)
                if arr_p is None:
                    continue
                if nneg in (None, "0"):
                    arr = list(arr_p)
                else:
                    arr_n = V.get(nneg)
                    if arr_n is None:
                        arr = list(arr_p)
                    else:
                        arr = [a - b for a, b in zip(arr_p, arr_n)]
                data[f"V({pid})"] = arr
            else:
                arr = V.get(info)
                if arr is not None:
                    data[f"V({pid})"] = arr
        for pid, vsname in aliases.get("currents", {}).items():
            arr = I.get(vsname)
            if arr is not None:
                data[f"I({pid})"] = arr
        for n, arr in V.items():
            data.setdefault(f"V({n})", arr)
        for n, arr in I.items():
            data.setdefault(f"I({n})", arr)

        self._signal_data = data
        self._available = list(data.keys())
        self._info.setText(f"{len(self._t)} samples · "
                           f"{len(self._available)} signals")

        # First-result auto layout: replace pristine state with V/I split.
        first_run = (not self._user_customised
                     and len(self._panels) == 1
                     and not any(self._panels[0].axis_state().get(s, 0)
                                 for s in self._panels[0]._axis))
        if first_run:
            self._split_v_i()
            self._user_customised = True
            return

        for panel in self._panels:
            panel.set_available_signals(self._available)
