"""PCS profile controller.

Resolves the user-facing PCS ``mode`` (CC / CV / CP / CCCV / CPCV /
CYCLE — plus the legacy V_DC / I_DC / P_DC) into per-step "active"
setpoints that the linear / nonlinear stamps consume.

Sign convention (DC side):
    + = charge  (PCS sources current/power INTO the battery)
    − = discharge (PCS sinks current/power FROM the battery)

For each PCS element, the controller maintains a small state machine
in ``elem.params["_state"]`` and writes the resolved setpoint into
``elem.params["_active_mode"]`` ∈ {"V_DC", "I_DC", "P_DC"} together
with ``_active_V_DC`` / ``_active_I_DC`` / ``_active_P_DC``.  The
stamping code in ``mna.py`` and ``nonlinear.py`` only ever reads the
``_active_*`` fields.
"""
from __future__ import annotations

import json
from typing import Any, Dict


# Public alias of legacy → active mode (used when the user picks
# V_DC/I_DC/P_DC directly).
_LEGACY_MAP = {"V_DC": "V_DC", "I_DC": "I_DC", "P_DC": "P_DC"}


def _node_v(x_prev, node: str, n_nodes: int, node_index: Dict[str, int]) -> float:
    if node == "0" or x_prev is None:
        return 0.0
    i = node_index.get(node)
    if i is None:
        return 0.0
    return float(x_prev[i])


def _vs_current(x_prev, name: str, n_nodes: int, vs_index: Dict[str, int]) -> float:
    """Return the previous-step current through the named vsource branch.
    Sign: positive means current entering the + node from the source."""
    if x_prev is None:
        return 0.0
    idx = vs_index.get(name)
    if idx is None:
        return 0.0
    return float(x_prev[n_nodes + idx])


def _ensure_steps(elem) -> list:
    """Coerce cycle_steps param into a list of dicts."""
    raw = elem.params.get("cycle_steps", [])
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            steps: list = []
        else:
            try:
                steps = json.loads(s)
                if not isinstance(steps, list):
                    steps = []
            except Exception:
                steps = []
        elem.params["cycle_steps"] = steps
        return steps
    return list(raw) if isinstance(raw, list) else []


def _set_active(elem, mode: str, *, v=None, i=None, p=None) -> None:
    elem.params["_active_mode"] = mode
    if mode == "V_DC":
        elem.params["_active_V_DC"] = float(v if v is not None else 0.0)
    elif mode == "I_DC":
        elem.params["_active_I_DC"] = float(i if i is not None else 0.0)
    elif mode == "P_DC":
        elem.params["_active_P_DC"] = float(p if p is not None else 0.0)


def _apply_simple(elem, sub_mode: str, params: Dict[str, Any]) -> None:
    """Map a simple sub-mode (CC/CV/CP/REST/DONE) to active fields."""
    if sub_mode == "CC":
        _set_active(elem, "I_DC", i=params.get("I", 0.0))
    elif sub_mode == "CV":
        _set_active(elem, "V_DC", v=params.get("V", 0.0))
    elif sub_mode == "CP":
        _set_active(elem, "P_DC", p=params.get("P", 0.0))
    elif sub_mode in ("REST", "DONE"):
        _set_active(elem, "I_DC", i=0.0)
    else:
        _set_active(elem, "I_DC", i=0.0)


def _check_terminate(state, params, t, V_dc, I_dc, charging: bool) -> bool:
    """Return True if any termination condition for the active sub-step
    is satisfied."""
    t0 = state.get("phase_t0", t)
    if "max_time" in params and (t - t0) >= float(params["max_time"]):
        return True
    if "time" in params and (t - t0) >= float(params["time"]):
        return True
    if charging:
        if "V_max" in params and V_dc >= float(params["V_max"]):
            return True
    else:
        if "V_min" in params and V_dc <= float(params["V_min"]):
            return True
    if "I_term" in params:
        # |I| dropping below threshold (taper)
        if abs(I_dc) <= float(params["I_term"]):
            return True
    return False


def update_pcs_controllers(netlist, t: float, x_prev, vs_index, node_index,
                           n_nodes: int) -> None:
    """Walk every PCS element and refresh its _active_* fields."""
    for elem in netlist.elements:
        if elem.kind != "PCS":
            continue
        _update_one(elem, t, x_prev, vs_index, node_index, n_nodes)


def _update_one(elem, t, x_prev, vs_index, node_index, n_nodes) -> None:
    p = elem.params
    mode = str(p.get("mode", "V_DC"))

    # Measure DC side from previous solution.
    n_pos, n_neg = elem.nodes[2], elem.nodes[3]
    V_dc = (_node_v(x_prev, n_pos, n_nodes, node_index)
            - _node_v(x_prev, n_neg, n_nodes, node_index))
    I_dc = _vs_current(x_prev, elem.name, n_nodes, vs_index)

    # State container.
    state = p.setdefault("_state", {"phase": None, "phase_t0": t,
                                    "step_idx": 0, "cycle_n": 0})

    # ---------------- Legacy direct modes ----------------
    if mode in _LEGACY_MAP:
        if mode == "V_DC":
            _set_active(elem, "V_DC", v=p.get("V_DC_set", 0.0))
        elif mode == "I_DC":
            _set_active(elem, "I_DC", i=p.get("I_DC_set", 0.0))
        else:
            _set_active(elem, "P_DC", p=p.get("P_DC_set", 0.0))
        return

    # ---------------- Single-mode profiles ----------------
    if mode == "CC":
        _set_active(elem, "I_DC", i=p.get("I_set", 0.0))
        return
    if mode == "CV":
        _set_active(elem, "V_DC", v=p.get("V_set", 0.0))
        return
    if mode == "CP":
        _set_active(elem, "P_DC", p=p.get("P_set", 0.0))
        return

    # ---------------- CCCV / CPCV ----------------
    if mode in ("CCCV", "CPCV"):
        first_phase = "CC" if mode == "CCCV" else "CP"
        if state["phase"] is None:
            state["phase"] = first_phase
            state["phase_t0"] = t

        I_set = float(p.get("I_set", 0.0))
        P_set = float(p.get("P_set", 0.0))
        V_max = float(p.get("V_max", 0.0))
        V_min = float(p.get("V_min", 0.0))
        I_term = float(p.get("I_term", 0.0))
        charging = (I_set >= 0 if mode == "CCCV" else P_set >= 0)

        # CC/CP → CV transition on V limit (charge: V_max; discharge: V_min)
        if state["phase"] in ("CC", "CP"):
            if charging and V_max > 0 and V_dc >= V_max:
                state["phase"] = "CV"
                state["phase_t0"] = t
            elif (not charging) and V_min > 0 and V_dc <= V_min:
                state["phase"] = "CV"
                state["phase_t0"] = t
        # CV → DONE on current taper
        if state["phase"] == "CV" and I_term > 0 and abs(I_dc) <= I_term:
            state["phase"] = "DONE"
            state["phase_t0"] = t

        if state["phase"] == "CC":
            _set_active(elem, "I_DC", i=I_set)
        elif state["phase"] == "CP":
            _set_active(elem, "P_DC", p=P_set)
        elif state["phase"] == "CV":
            v_target = V_max if charging else V_min
            _set_active(elem, "V_DC", v=v_target)
        else:  # DONE
            _set_active(elem, "I_DC", i=0.0)
        return

    # ---------------- CYCLE ----------------
    if mode == "CYCLE":
        steps = _ensure_steps(elem)
        repeat = int(p.get("cycle_repeat", 1))
        if not steps:
            _set_active(elem, "I_DC", i=0.0)
            return

        if state["phase"] is None:
            state["step_idx"] = 0
            state["cycle_n"] = 0
            state["phase_t0"] = t
            state["phase"] = "step"
            state["sub"] = None  # CCCV/CPCV inner phase tracker

        idx = state["step_idx"]
        if idx >= len(steps):
            state["cycle_n"] += 1
            if state["cycle_n"] >= repeat:
                _set_active(elem, "I_DC", i=0.0)
                return
            state["step_idx"] = 0
            state["phase_t0"] = t
            state["sub"] = None
            idx = 0

        step = steps[idx] if isinstance(steps[idx], dict) else {}
        sm = str(step.get("mode", "REST")).upper()

        # For CCCV/CPCV inside a step, we need a tiny inner state.
        sub = state.get("sub")
        first_inner = "CC" if sm == "CCCV" else ("CP" if sm == "CPCV" else None)
        if first_inner is not None and sub is None:
            state["sub"] = first_inner
            sub = first_inner

        # Determine direction (charge/discharge) for this step.
        I_step = float(step.get("I", 0.0))
        P_step = float(step.get("P", 0.0))
        charging = (I_step >= 0 if sm in ("CC", "CCCV") else
                    (P_step >= 0 if sm in ("CP", "CPCV") else True))

        # Termination check for the step / inner phase.
        terminate_step = False
        if sm in ("CC", "CV", "CP", "REST"):
            terminate_step = _check_terminate(
                {"phase_t0": state["phase_t0"]}, step, t, V_dc, I_dc, charging)
        elif sm in ("CCCV", "CPCV"):
            V_max = float(step.get("V_max", 0.0))
            V_min = float(step.get("V_min", 0.0))
            I_term = float(step.get("I_term", 0.0))
            if sub in ("CC", "CP"):
                if charging and V_max > 0 and V_dc >= V_max:
                    state["sub"] = "CV"
                    state["phase_t0"] = t
                elif (not charging) and V_min > 0 and V_dc <= V_min:
                    state["sub"] = "CV"
                    state["phase_t0"] = t
                # max_time on whole step
                if "max_time" in step and (t - state["phase_t0"]) >= float(step["max_time"]):
                    terminate_step = True
            elif sub == "CV":
                if I_term > 0 and abs(I_dc) <= I_term:
                    terminate_step = True
                if "max_time" in step and (t - state["phase_t0"]) >= float(step["max_time"]):
                    terminate_step = True

        if terminate_step:
            state["step_idx"] = idx + 1
            state["phase_t0"] = t
            state["sub"] = None
            # Re-resolve next step on the *next* call; for now, drive 0.
            _set_active(elem, "I_DC", i=0.0)
            return

        # Apply currently-active sub-step output.
        if sm == "CC":
            _set_active(elem, "I_DC", i=I_step)
        elif sm == "CV":
            _set_active(elem, "V_DC", v=float(step.get("V", 0.0)))
        elif sm == "CP":
            _set_active(elem, "P_DC", p=P_step)
        elif sm == "REST":
            _set_active(elem, "I_DC", i=0.0)
        elif sm in ("CCCV", "CPCV"):
            if sub == "CC":
                _set_active(elem, "I_DC", i=I_step)
            elif sub == "CP":
                _set_active(elem, "P_DC", p=P_step)
            elif sub == "CV":
                v_target = (float(step.get("V_max", 0.0)) if charging
                            else float(step.get("V_min", 0.0)))
                _set_active(elem, "V_DC", v=v_target)
            else:
                _set_active(elem, "I_DC", i=0.0)
        else:
            _set_active(elem, "I_DC", i=0.0)
        return

    # Fallback
    _set_active(elem, "V_DC", v=p.get("V_DC_set", 0.0))
