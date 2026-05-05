"""Phase-3 nonlinear solver: Newton-Raphson MNA with Diode + MOSFET stamps.

We extend the linear MNA with iterative companion-model linearisation for
nonlinear elements, evaluated at each time step.
"""
from __future__ import annotations

import math
import numpy as np

from .netlist import Netlist
from .mna import MNASystem, GND_LABELS


class NonlinearMNASystem(MNASystem):
    MAX_ITER = 50
    TOL = 1e-6

    def _node_voltage_x(self, x: np.ndarray, node: str) -> float:
        if node in GND_LABELS:
            return 0.0
        return float(x[self.node_index[node]])

    # Nonlinear stamps (companion model)
    def _stamp_diode(self, A, b, e, x_guess):
        Vt = float(e.params.get("Vt", 0.02585))
        Is = float(e.params.get("Is", 1e-12))
        n = float(e.params.get("n", 1.0))
        Vd = self._node_voltage_x(x_guess, e.nodes[0]) - \
             self._node_voltage_x(x_guess, e.nodes[1])
        Vd = max(min(Vd, 0.8), -2.0)  # clamp for stability
        Id = Is * (math.exp(Vd / (n * Vt)) - 1.0)
        gd = (Is / (n * Vt)) * math.exp(Vd / (n * Vt))
        Ieq = Id - gd * Vd
        # Stamp conductance gd between nodes
        self._stamp_admittance(A, e.nodes[0], e.nodes[1], gd)
        # And current source Ieq from anode -> cathode
        self._stamp_current(b, e.nodes[0], e.nodes[1], Ieq)

    def _stamp_mosfet(self, A, b, e, x_guess):
        # Simple Level-1 NMOS: nodes = [D, G, S]
        D, G, S = e.nodes
        Kp = float(e.params.get("Kp", 2e-4))
        Vth = float(e.params.get("Vth", 1.0))
        lam = float(e.params.get("lambda", 0.0))
        Vd = self._node_voltage_x(x_guess, D)
        Vg = self._node_voltage_x(x_guess, G)
        Vs = self._node_voltage_x(x_guess, S)
        Vgs = Vg - Vs
        Vds = Vd - Vs
        if Vgs <= Vth:
            Id = 0.0
            gds = 1e-12
            gm = 0.0
        elif Vds < Vgs - Vth:  # triode
            Id = Kp * ((Vgs - Vth) * Vds - 0.5 * Vds * Vds) * (1 + lam * Vds)
            gm = Kp * Vds
            gds = Kp * (Vgs - Vth - Vds)
        else:  # saturation
            Id = 0.5 * Kp * (Vgs - Vth) ** 2 * (1 + lam * Vds)
            gm = Kp * (Vgs - Vth) * (1 + lam * Vds)
            gds = 0.5 * Kp * lam * (Vgs - Vth) ** 2
        # Linearised: Ids ~ Id0 + gm*(Vgs - Vgs0) + gds*(Vds - Vds0)
        Ieq = Id - gm * Vgs - gds * Vds
        # Stamp gds across D-S
        self._stamp_admittance(A, D, S, gds)
        # Stamp gm: current from D->S = gm * (Vg - Vs)  -> contributes to KCL
        # K[D,G] += gm, K[D,S] -= gm, K[S,G] -= gm, K[S,S] += gm
        iD, iG, iS = self._ni(D), self._ni(G), self._ni(S)
        if iD >= 0 and iG >= 0:
            A[iD, iG] += gm
        if iD >= 0 and iS >= 0:
            A[iD, iS] -= gm
        if iS >= 0 and iG >= 0:
            A[iS, iG] -= gm
        if iS >= 0:
            A[iS, iS] += gm
        # Equivalent current source: D->S
        self._stamp_current(b, D, S, Ieq)

    def _stamp_pconst(self, A, b, e, x_guess):
        """Constant-power load: positive P sinks power from pin0 to pin1.
        I(V) = P / V → linearise via Newton.
        For a LOAD (current drained out of pin0), the Norton has
        g = -P/V_g² (negative-slope effective admittance) and
        I_eq = 2·I0 = 2·P/V_g."""
        P = float(e.params.get("P", 0.0))
        Vd = (self._node_voltage_x(x_guess, e.nodes[0])
              - self._node_voltage_x(x_guess, e.nodes[1]))
        # Clamp to keep the iteration well-conditioned (esp. from x = 0 start).
        VMIN = 0.5
        if abs(Vd) < VMIN:
            Vd = VMIN if Vd >= 0 else -VMIN
        I0 = P / Vd
        g = -P / (Vd * Vd)
        Ieq = I0 - g * Vd  # = 2 * I0
        self._stamp_admittance(A, e.nodes[0], e.nodes[1], g)
        # Current flows from pin0 -> pin1 (P > 0 = load on +pin)
        self._stamp_current(b, e.nodes[0], e.nodes[1], Ieq)

    def _stamp_pcs_ac(self, A, b, e, x_guess):
        """AC-side stamp for PCS — instantaneous P load matched to DC side.

        To avoid Newton-loop instability the DC current is read from the
        previous *timestep's* converged value (stored in
        ``e.params['_I_dc_last']`` by ``solve_transient``), not from the
        current Newton iterate.  V_DC mode also uses the active setpoint."""
        a_mode = str(e.params.get(
            "_active_mode",
            e.params.get("mode", "V_DC")
            if e.params.get("mode") in ("V_DC", "I_DC", "P_DC") else "V_DC"))
        eta = max(float(e.params.get("eta", 0.98)), 0.05)
        I_dc_last = float(e.params.get("_I_dc_last", 0.0))
        if a_mode == "V_DC":
            V_dc = float(e.params.get(
                "_active_V_DC", e.params.get("V_DC_set", 0.0)))
            P_dc = V_dc * I_dc_last
        elif a_mode == "I_DC":
            V_dc_last = float(e.params.get("_V_dc_last", 0.0))
            I_dc = float(e.params.get(
                "_active_I_DC", e.params.get("I_DC_set", 0.0)))
            P_dc = V_dc_last * I_dc
        elif a_mode == "P_DC":
            P_dc = float(e.params.get(
                "_active_P_DC", e.params.get("P_DC_set", 0.0)))
        else:
            P_dc = 0.0
        if P_dc >= 0:
            P_ac = P_dc / eta
        else:
            P_ac = P_dc * eta
        Vd = (self._node_voltage_x(x_guess, e.nodes[0])
              - self._node_voltage_x(x_guess, e.nodes[1]))
        VMIN = 1.0
        if abs(Vd) < VMIN:
            Vd = VMIN if Vd >= 0 else -VMIN
        I0 = P_ac / Vd
        g = -P_ac / (Vd * Vd)
        Ieq = I0 - g * Vd
        self._stamp_admittance(A, e.nodes[0], e.nodes[1], g)
        self._stamp_current(b, e.nodes[0], e.nodes[1], Ieq)

    def _stamp_pcs_dc_pmode(self, A, b, e, x_guess):
        """DC-side constant-power stamp when active mode is P_DC.

        Adds Newton-linearised Norton on (DC+, DC-) and overwrites the
        observer row so that Iv reports the actual instantaneous current.
        """
        P_dc = float(e.params.get(
            "_active_P_DC", e.params.get("P_DC_set", 0.0)))
        Vd = (self._node_voltage_x(x_guess, e.nodes[2])
              - self._node_voltage_x(x_guess, e.nodes[3]))
        VMIN = 1.0
        if abs(Vd) < VMIN:
            Vd = VMIN if Vd >= 0 else -VMIN
        I0 = P_dc / Vd
        g = P_dc / (Vd * Vd)
        Ieq = 2.0 * I0
        # Norton on DC port (sign matches I_DC mode: +P = charge → source).
        self._stamp_admittance(A, e.nodes[2], e.nodes[3], g)
        self._stamp_current(b, e.nodes[3], e.nodes[2], Ieq)
        # Observer row: iv = Ieq - g*(V+ - V-)  (= actual through-current at
        # convergence, NOT the linearisation point).  For Norton I_eq + g*V
        # convention, the actual current source-side at + node equals
        # I_eq - g*Vd (current INTO + from the source).
        idx = self.vs_index[e.name]
        vs_row = self.n_nodes + idx
        ip = self._ni(e.nodes[2])
        in_ = self._ni(e.nodes[3])
        # mna.build already added A[vs_row, vs_row] += 1.0
        if ip >= 0:
            A[vs_row, ip] += g
        if in_ >= 0:
            A[vs_row, in_] -= g
        b[vs_row] += Ieq

    def build_nonlinear(self, x_prev, dt, t, x_guess):
        A, b = self.build(x_prev, dt, t)
        for e in self.netlist.elements:
            if e.kind == "DIODE":
                self._stamp_diode(A, b, e, x_guess)
            elif e.kind == "MOSFET":
                self._stamp_mosfet(A, b, e, x_guess)
            elif e.kind == "PCONST":
                self._stamp_pconst(A, b, e, x_guess)
            elif e.kind == "BUS" and str(e.params.get("mode", "Grid")) == "PLoad":
                self._stamp_pconst(A, b, e, x_guess)
            elif e.kind == "PCS":
                self._stamp_pcs_ac(A, b, e, x_guess)
                a_mode = str(e.params.get(
                    "_active_mode",
                    e.params.get("mode", "V_DC")
                    if e.params.get("mode") in ("V_DC", "I_DC", "P_DC")
                    else "V_DC"))
                if a_mode == "P_DC":
                    self._stamp_pcs_dc_pmode(A, b, e, x_guess)
        return A, b


def _has_nonlinear(netlist: Netlist) -> bool:
    for e in netlist.elements:
        if e.kind in ("DIODE", "MOSFET", "PCONST", "PCS"):
            return True
        if e.kind == "BUS" and str(e.params.get("mode", "Grid")) == "PLoad":
            return True
    return False


def solve_nonlinear_step(sys: NonlinearMNASystem, x_prev, dt, t, x_init=None):
    x = x_init.copy() if x_init is not None else np.zeros(sys.size)
    # Adaptive damping: tighter when iterations stall to handle constant-power
    # Norton stamps that can have negative effective conductance.
    damp = 0.7
    for it in range(sys.MAX_ITER):
        A, b = sys.build_nonlinear(x_prev, dt, t, x)
        try:
            x_new = np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            x_new = x
        delta = x_new - x
        if np.linalg.norm(delta, ord=np.inf) < sys.TOL:
            return x_new
        # Increase damping on large jumps (helps when V crosses zero on a
        # constant-power stamp and Newton wants to jump to the unstable
        # high-current low-voltage branch).
        norm = float(np.linalg.norm(delta, ord=np.inf))
        if norm > 5.0 and it > 2:
            damp = 0.3
        x = damp * x_new + (1.0 - damp) * x
    return x


def solve_dc(netlist: Netlist):
    sys = NonlinearMNASystem(netlist)
    if _has_nonlinear(netlist):
        x = solve_nonlinear_step(sys, x_prev=None, dt=None, t=0.0)
    else:
        A, b = sys.build(None, None, 0.0)
        x = np.linalg.solve(A, b)
    return sys, x


def solve_transient(netlist: Netlist, t_end: float, dt: float, on_step=None,
                    on_progress=None):
    from .pcs_control import update_pcs_controllers
    sys = NonlinearMNASystem(netlist)
    nonlinear = _has_nonlinear(netlist)
    # Initial setpoint resolution (uses x_prev=None → V/I default to 0).
    update_pcs_controllers(netlist, 0.0, None, sys.vs_index, sys.node_index,
                           sys.n_nodes)
    # Initial DC point
    if nonlinear:
        x = solve_nonlinear_step(sys, x_prev=None, dt=None, t=0.0)
    else:
        A0, b0 = sys.build(None, None, 0.0)
        try:
            x = np.linalg.solve(A0, b0)
        except np.linalg.LinAlgError:
            x = np.zeros(sys.size)

    n_steps = int(round(t_end / dt))
    ts = np.linspace(0.0, n_steps * dt, n_steps + 1)
    V_hist = {n: np.zeros(n_steps + 1) for n in sys.node_index}
    I_hist = {e.name: np.zeros(n_steps + 1) for e in sys.vs_elems}

    for k, tval in enumerate(ts):
        if k > 0:
            # Refresh PCS profile setpoints based on *previous* solution.
            update_pcs_controllers(netlist, tval, x, sys.vs_index,
                                   sys.node_index, sys.n_nodes)
            if nonlinear:
                x = solve_nonlinear_step(sys, x_prev=x, dt=dt, t=tval, x_init=x)
            else:
                A, b = sys.build(x, dt, tval)
                x = np.linalg.solve(A, b)
        for n, i in sys.node_index.items():
            V_hist[n][k] = x[i]
        for e in sys.vs_elems:
            I_hist[e.name][k] = sys.vs_current(x, e.name)
        for e in sys.netlist.elements:
            if e.kind == "BATTERY" and e.model is not None and hasattr(e.model, "update"):
                I_batt = sys.vs_current(x, e.name)
                e.model.update(I=I_batt, dt=dt if k > 0 else 0.0, t=tval)
            if e.kind == "PCS":
                # Cache converged DC current/voltage for next step's AC stamp.
                e.params["_I_dc_last"] = float(sys.vs_current(x, e.name))
                try:
                    vp = x[sys.node_index[e.nodes[2]]] if e.nodes[2] in sys.node_index else 0.0
                    vn = x[sys.node_index[e.nodes[3]]] if e.nodes[3] in sys.node_index else 0.0
                    e.params["_V_dc_last"] = float(vp - vn)
                except Exception:
                    e.params["_V_dc_last"] = 0.0
        if on_step is not None:
            on_step(k, tval, x)
        if on_progress is not None:
            on_progress(k, n_steps, ts, V_hist, I_hist)

    return {"t": ts, "V": V_hist, "I": I_hist, "system": sys}
