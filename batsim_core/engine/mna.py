"""Modified Nodal Analysis (MNA) engine.

Supports DC operating point and transient analysis with
Backward Euler integration. Linear elements: R, V, I, C, L.
Battery elements expose a `stamp(...)` method via their model object.
"""
from __future__ import annotations

import numpy as np

from .netlist import Netlist, Element


GND_LABELS = {"0", "GND"}


class MNASystem:
    def __init__(self, netlist: Netlist):
        self.netlist = netlist
        nodes = [n for n in netlist.nodes if n not in GND_LABELS]
        self.node_index: dict[str, int] = {n: i for i, n in enumerate(nodes)}
        # Voltage-source-like elements need an extra current unknown.
        self.vs_elems: list[Element] = []
        for e in netlist.elements:
            if e.kind in ("V", "L", "BATTERY", "BATPACK", "BATRACK", "IPROBE", "TR", "GRID"):
                self.vs_elems.append(e)
            elif e.kind == "BUS" and str(e.params.get("mode", "Grid")) == "Grid":
                self.vs_elems.append(e)
            elif e.kind == "PCS":
                # The DC side is always a stiff V source; AC side is
                # treated as a (possibly nonlinear) power port.
                self.vs_elems.append(e)
        self.vs_index: dict[str, int] = {e.name: i for i, e in enumerate(self.vs_elems)}
        self.n_nodes = len(self.node_index)
        self.n_vs = len(self.vs_elems)
        self.size = self.n_nodes + self.n_vs

    # ---- helpers ----
    def _ni(self, node: str) -> int:
        return -1 if node in GND_LABELS else self.node_index[node]

    def _stamp_admittance(self, A: np.ndarray, n1: str, n2: str, g: float) -> None:
        i, j = self._ni(n1), self._ni(n2)
        if i >= 0:
            A[i, i] += g
        if j >= 0:
            A[j, j] += g
        if i >= 0 and j >= 0:
            A[i, j] -= g
            A[j, i] -= g

    def _stamp_current(self, b: np.ndarray, n_from: str, n_to: str, I: float) -> None:
        # Current flowing from n_from -> n_to (leaves n_from, enters n_to)
        i, j = self._ni(n_from), self._ni(n_to)
        if i >= 0:
            b[i] -= I
        if j >= 0:
            b[j] += I

    def _stamp_vsource(self, A: np.ndarray, b: np.ndarray, idx: int,
                       n_pos: str, n_neg: str, V: float) -> None:
        row = self.n_nodes + idx
        ip, in_ = self._ni(n_pos), self._ni(n_neg)
        if ip >= 0:
            A[ip, row] += 1.0
            A[row, ip] += 1.0
        if in_ >= 0:
            A[in_, row] -= 1.0
            A[row, in_] -= 1.0
        b[row] += V

    # ---- builders ----
    def build(self, x_prev: np.ndarray | None, dt: float | None,
              t: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
        """Build A x = b for one time step.
        If dt is None -> DC analysis (capacitors open, inductors short).
        """
        A = np.zeros((self.size, self.size))
        b = np.zeros(self.size)

        for e in self.netlist.elements:
            if e.kind == "R":
                R = float(e.params.get("R", 1e3))
                self._stamp_admittance(A, e.nodes[0], e.nodes[1], 1.0 / R)

            elif e.kind == "I":
                I = float(e.params.get("I", 0.0))
                self._stamp_current(b, e.nodes[0], e.nodes[1], I)

            elif e.kind == "ICONST":
                I = float(e.params.get("I", 0.0))
                self._stamp_current(b, e.nodes[0], e.nodes[1], I)

            elif e.kind == "IPATTERN":
                wf = e.params.get("_wf")
                if wf is None:
                    from .sources import make_csv_waveform
                    wf = make_csv_waveform(
                        e.params.get("csv", ""),
                        float(e.params.get("scale", 1.0)),
                        bool(e.params.get("repeat", True)),
                        float(e.params.get("I", 0.0)))
                    e.params["_wf"] = wf
                I = float(wf(t))
                self._stamp_current(b, e.nodes[0], e.nodes[1], I)

            elif e.kind == "V":
                V = float(e.params.get("V", 0.0))
                if "waveform" in e.params:
                    V = float(e.params["waveform"](t))
                idx = self.vs_index[e.name]
                self._stamp_vsource(A, b, idx, e.nodes[0], e.nodes[1], V)

            elif e.kind == "C":
                C = float(e.params.get("C", 1e-6))
                if dt is None:
                    continue  # open at DC
                g = C / dt
                self._stamp_admittance(A, e.nodes[0], e.nodes[1], g)
                # Companion current source: i = g * v(t-dt)
                v_prev = self._node_voltage(x_prev, e.nodes[0]) - \
                         self._node_voltage(x_prev, e.nodes[1])
                Ieq = g * v_prev
                self._stamp_current(b, e.nodes[1], e.nodes[0], Ieq)

            elif e.kind == "L":
                L = float(e.params.get("L", 1e-3))
                idx = self.vs_index[e.name]
                if dt is None:
                    self._stamp_vsource(A, b, idx, e.nodes[0], e.nodes[1], 0.0)
                else:
                    # v = L/dt (i - i_prev)  ->  treat as VS with V_eq = (L/dt)*i_prev
                    # but we have unknown i; rewrite as: v - (L/dt) i = -(L/dt) i_prev
                    # Modify the VS row so that diagonal subtracts L/dt and rhs += -(L/dt) i_prev
                    self._stamp_vsource(A, b, idx, e.nodes[0], e.nodes[1], 0.0)
                    row = self.n_nodes + idx
                    A[row, row] -= L / dt
                    i_prev = x_prev[row] if x_prev is not None else 0.0
                    b[row] += -(L / dt) * i_prev

            elif e.kind == "BATTERY":
                # Delegate to model.stamp(); falls back to ideal V if no model.
                model = e.model
                idx = self.vs_index[e.name]
                if model is not None and hasattr(model, "terminal_voltage"):
                    Vt = float(model.terminal_voltage(t, dt))
                else:
                    Vt = float(e.params.get("V", 3.7))
                self._stamp_vsource(A, b, idx, e.nodes[0], e.nodes[1], Vt)

            elif e.kind == "BATPACK":
                model = e.model
                idx = self.vs_index[e.name]
                if model is not None and hasattr(model, "terminal_voltage"):
                    Vt = float(model.terminal_voltage(t, dt))
                else:
                    Vt = float(e.params.get("V", 3.7))
                self._stamp_vsource(A, b, idx, e.nodes[0], e.nodes[1], Vt)

            elif e.kind == "BATRACK":
                model = e.model
                idx = self.vs_index[e.name]
                if model is not None and hasattr(model, "terminal_voltage"):
                    Vt = float(model.terminal_voltage(t, dt))
                else:
                    Vt = float(e.params.get("V", 3.7))
                self._stamp_vsource(A, b, idx, e.nodes[0], e.nodes[1], Vt)

            elif e.kind == "SWITCH":
                closed = bool(e.params.get("closed", True))
                R = 1e-3 if closed else 1e9
                self._stamp_admittance(A, e.nodes[0], e.nodes[1], 1.0 / R)

            elif e.kind == "GND":
                pass  # handled by node naming
            elif e.kind == "IPROBE":
                # Zero-volt source so we capture the through-current.
                idx = self.vs_index[e.name]
                self._stamp_vsource(A, b, idx, e.nodes[0], e.nodes[1], 0.0)

            elif e.kind == "BUS":
                mode = str(e.params.get("mode", "Grid"))
                if mode == "Grid":
                    V = float(e.params.get("V", 0.0))
                    idx = self.vs_index[e.name]
                    self._stamp_vsource(A, b, idx, e.nodes[0], e.nodes[1], V)
                elif mode == "ILoad":
                    I = float(e.params.get("I", 0.0))
                    self._stamp_current(b, e.nodes[0], e.nodes[1], I)
                elif mode == "PLoad":
                    pass  # handled in NonlinearMNASystem.build_nonlinear
                else:
                    raise ValueError(f"Unknown BUS mode: {mode}")

            elif e.kind == "GRID":
                # AC sinusoidal source.  Cache the waveform on the params
                # dict so we don't rebuild it every step.
                wf = e.params.get("_wf")
                if wf is None:
                    from .sources import make_sine_waveform
                    wf = make_sine_waveform(
                        float(e.params.get("V_rms", 220.0)),
                        float(e.params.get("freq", 60.0)),
                        float(e.params.get("phase_deg", 0.0)),
                        float(e.params.get("offset", 0.0)))
                    e.params["_wf"] = wf
                V = float(wf(t))
                idx = self.vs_index[e.name]
                self._stamp_vsource(A, b, idx, e.nodes[0], e.nodes[1], V)

            elif e.kind == "PCS":
                # Resolved by pcs_control.update_pcs_controllers each step.
                a_mode = str(e.params.get(
                    "_active_mode",
                    e.params.get("mode", "V_DC")
                    if e.params.get("mode") in ("V_DC", "I_DC", "P_DC")
                    else "V_DC"))
                idx = self.vs_index[e.name]
                vs_row = self.n_nodes + idx
                if a_mode == "V_DC":
                    V_dc = float(e.params.get(
                        "_active_V_DC", e.params.get("V_DC_set", 0.0)))
                    self._stamp_vsource(A, b, idx, e.nodes[2], e.nodes[3], V_dc)
                elif a_mode == "I_DC":
                    I_dc = float(e.params.get(
                        "_active_I_DC", e.params.get("I_DC_set", 0.0)))
                    # Observer row: Iv = I_dc (decoupled from node voltages).
                    A[vs_row, vs_row] += 1.0
                    b[vs_row] += I_dc
                    # Pure Norton injection on DC port.  Convention:
                    # +I_dc = charging  (PCS sources current OUT of DC+).
                    # _stamp_current(b, p, n, I) means internal flow p→n,
                    # so for sourcing at DC+ we use n_from=DC-, n_to=DC+.
                    self._stamp_current(b, e.nodes[3], e.nodes[2], I_dc)
                    self._stamp_admittance(A, e.nodes[2], e.nodes[3], 1e-9)
                elif a_mode == "P_DC":
                    # Observer placeholder; the nonlinear builder overwrites
                    # both the vs row and the DC-side Norton stamp.
                    A[vs_row, vs_row] += 1.0
                else:
                    raise ValueError(f"Unknown PCS active mode: {a_mode}")

            elif e.kind == "TR":
                # Ideal DC turns-ratio coupler.
                # Pins: [p+, p-, s+, s-];  V(p+)-V(p-) = n * (V(s+)-V(s-))
                # Auxiliary current Ip flows into p+ and out of p-.
                # Power balance fixes Is = -n * Ip (into s+, out of s-).
                n_ratio = float(e.params.get("n", 1.0))
                idx = self.vs_index[e.name]
                row = self.n_nodes + idx
                pp, pn, sp, sn = (self._ni(e.nodes[0]),
                                  self._ni(e.nodes[1]),
                                  self._ni(e.nodes[2]),
                                  self._ni(e.nodes[3]))
                # KCL contributions of Ip (column "row") into each node:
                if pp >= 0:
                    A[pp, row] += 1.0
                    A[row, pp] += 1.0
                if pn >= 0:
                    A[pn, row] -= 1.0
                    A[row, pn] -= 1.0
                if sp >= 0:
                    A[sp, row] -= n_ratio
                    A[row, sp] -= n_ratio
                if sn >= 0:
                    A[sn, row] += n_ratio
                    A[row, sn] += n_ratio
                # Constraint b[row] = 0 (no source value).

            elif e.kind in ("DIODE", "MOSFET", "PCONST"):
                # Nonlinear elements: handled by NonlinearMNASystem in a separate
                # pass. In the linear base class, contribute nothing here.
                pass
            else:
                raise NotImplementedError(f"Unknown element kind: {e.kind}")

        return A, b

    # ---- post-processing ----
    def _node_voltage(self, x: np.ndarray | None, node: str) -> float:
        if node in GND_LABELS or x is None:
            return 0.0
        return float(x[self.node_index[node]])

    def vs_current(self, x: np.ndarray, name: str) -> float:
        idx = self.vs_index[name]
        return float(x[self.n_nodes + idx])

    def node_voltages(self, x: np.ndarray) -> dict[str, float]:
        out = {n: float(x[i]) for n, i in self.node_index.items()}
        out["0"] = 0.0
        out["GND"] = 0.0
        return out


def solve_dc(netlist: Netlist) -> tuple[MNASystem, np.ndarray]:
    sys = MNASystem(netlist)
    A, b = sys.build(x_prev=None, dt=None, t=0.0)
    x = np.linalg.solve(A, b)
    return sys, x


def solve_transient(netlist: Netlist, t_end: float, dt: float,
                    on_step=None, on_progress=None) -> dict:
    """Backward Euler transient. Returns time series of node voltages and
    voltage-source currents (which include battery currents)."""
    sys = MNASystem(netlist)
    # DC operating point as initial state
    A0, b0 = sys.build(x_prev=None, dt=None, t=0.0)
    try:
        x = np.linalg.solve(A0, b0)
    except np.linalg.LinAlgError:
        x = np.zeros(sys.size)

    n_steps = int(round(t_end / dt))
    ts = np.linspace(0.0, n_steps * dt, n_steps + 1)
    V_hist = {n: np.zeros(n_steps + 1) for n in sys.node_index}
    I_hist = {e.name: np.zeros(n_steps + 1) for e in sys.vs_elems}

    for k, t in enumerate(ts):
        if k > 0:
            A, b = sys.build(x_prev=x, dt=dt, t=t)
            x = np.linalg.solve(A, b)
        for n, i in sys.node_index.items():
            V_hist[n][k] = x[i]
        for e in sys.vs_elems:
            I_hist[e.name][k] = sys.vs_current(x, e.name)
        # Allow models (e.g., battery) to update internal state
        for e in sys.netlist.elements:
            if e.kind in ("BATTERY", "BATPACK", "BATRACK") and e.model is not None and hasattr(e.model, "update"):
                I_batt = sys.vs_current(x, e.name)
                # Convention: positive current = discharging (out of + terminal)
                e.model.update(I=I_batt, dt=dt if k > 0 else 0.0, t=t)
        if on_step is not None:
            on_step(k, t, x)
        if on_progress is not None:
            on_progress(k, n_steps, ts, V_hist, I_hist)

    return {"t": ts, "V": V_hist, "I": I_hist, "system": sys}
