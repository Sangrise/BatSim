"""Example external SOC algorithm script for `batsim soc-eval --script`.

Run::

    batsim soc-eval --script examples/external_soc_example.py \
        --algorithm SimpleEKF SmoothedCC \
        --cell INR18650-25R --current 1.0 --t-end 1800 --dt 1.0
"""
from batsim_core.soc import register_soc_algorithm


@register_soc_algorithm("SimpleEKF")
class SimpleEKF:
    """Lightweight 1-state EKF using OCV(SOC) as the measurement model.

    State: SOC.  Process: SOC[k+1] = SOC[k] - I*dt/(3600*Q).
    Measurement: V = OCV(SOC) - I*R0  (simple Rint observation).
    """
    def __init__(self, capacity_Ah: float = 2.5, soc0: float = 1.0,
                 R0: float = 0.03, P0: float = 1e-3,
                 Q: float = 1e-6, R: float = 1e-3):
        self.cap = capacity_Ah
        self.soc = soc0
        self.R0 = R0
        self.P = P0
        self.Q = Q
        self.R = R

    def _ocv(self, soc):
        from batsim_core.models.base import default_ocv
        return default_ocv(soc)

    def _docv(self, soc, eps=1e-4):
        return (self._ocv(soc + eps) - self._ocv(soc - eps)) / (2 * eps)

    def step(self, I: float, V: float, dt: float) -> float:
        # Predict
        soc_p = self.soc - I * dt / 3600.0 / self.cap
        P_p = self.P + self.Q
        # Update
        H = self._docv(soc_p)
        y = V - (self._ocv(soc_p) - I * self.R0)
        S = H * P_p * H + self.R
        K = P_p * H / S
        self.soc = max(0.0, min(1.0, soc_p + K * y))
        self.P = (1 - K * H) * P_p
        return self.soc


@register_soc_algorithm("SmoothedCC")
def smoothed_cc(state, I, V, dt):
    """Function-style algorithm: low-pass-filtered Coulomb counting."""
    state.setdefault("soc", 1.0)
    state.setdefault("cap", 2.5)
    state.setdefault("alpha", 0.1)
    state.setdefault("I_filt", 0.0)
    state["I_filt"] = (1 - state["alpha"]) * state["I_filt"] + state["alpha"] * I
    state["soc"] -= state["I_filt"] * dt / 3600.0 / state["cap"]
    state["soc"] = max(0.0, min(1.0, state["soc"]))
    return state["soc"]

