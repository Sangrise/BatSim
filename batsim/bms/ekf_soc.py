"""Extended Kalman Filter SOC estimator for a Thevenin (1-RC) cell."""
from __future__ import annotations

import numpy as np


class EKFSocEstimator:
    """State: [SOC, V_rc].
    Measurement: V_t = OCV(SOC) - I*R0 - V_rc.
    Provide ocv(soc) and dOCV/dSOC. Defaults match models.base.default_ocv.
    """
    def __init__(self, capacity_Ah: float = 2.5, soc0: float = 1.0,
                 R0: float = 0.03, R1: float = 0.02, C1: float = 2000.0,
                 sigma_proc: float = 1e-6, sigma_meas: float = 1e-3):
        self.capacity_Ah = capacity_Ah
        self.R0, self.R1, self.C1 = R0, R1, C1
        self.x = np.array([soc0, 0.0])
        self.P = np.eye(2) * 1e-3
        self.Q = np.eye(2) * sigma_proc
        self.R = np.array([[sigma_meas]])

    def _ocv(self, soc: float) -> float:
        from batsim.models.base import default_ocv
        return default_ocv(soc)

    def _docv_dsoc(self, soc: float, eps: float = 1e-4) -> float:
        return (self._ocv(soc + eps) - self._ocv(soc - eps)) / (2 * eps)

    def step(self, I: float, V_meas: float, dt: float) -> float:
        # Predict
        soc, vrc = self.x
        soc_p = soc - I * dt / 3600.0 / self.capacity_Ah
        tau = self.R1 * self.C1
        vrc_p = vrc * (1 - dt / tau) + (dt / self.C1) * I
        F = np.array([[1.0, 0.0],
                      [0.0, 1.0 - dt / tau]])
        self.x = np.array([soc_p, vrc_p])
        self.P = F @ self.P @ F.T + self.Q

        # Update
        H = np.array([[self._docv_dsoc(soc_p), -1.0]])
        y = np.array([V_meas - (self._ocv(soc_p) - I * self.R0 - vrc_p)])
        S = H @ self.P @ H.T + self.R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + (K @ y).flatten()
        self.P = (np.eye(2) - K @ H) @ self.P
        self.x[0] = float(np.clip(self.x[0], 0.0, 1.0))
        return float(self.x[0])

    @property
    def soc(self) -> float:
        return float(self.x[0])
