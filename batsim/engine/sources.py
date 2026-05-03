"""Time-varying source helpers (CSV waveforms, common shapes).

These return a callable ``f(t) -> float`` consumed by the MNA stamps for
``IPATTERN`` / ``VPATTERN`` style elements. The callable is cached on the
element's ``params['_wf']`` slot to avoid re-parsing the CSV every step.
"""
from __future__ import annotations

import csv
import os
from typing import Callable

import numpy as np


def make_csv_waveform(path: str, scale: float = 1.0, repeat: bool = True,
                      default: float = 0.0) -> Callable[[float], float]:
    """Build a waveform sampler from a 2-column CSV (time, value).

    * Lines starting with ``#`` and blank rows are skipped.
    * If ``path`` is empty or the file is missing, returns a constant
      ``default`` lambda.
    * ``scale`` multiplies every value (use it for unit conversions).
    * ``repeat`` loops the pattern with period ``t_last``; otherwise the
      function clamps to the last sample.
    """
    if not path or not os.path.exists(path):
        return lambda t, _d=default: float(_d)
    ts: list[float] = []
    vs: list[float] = []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                cell = row[0].strip()
                if not cell or cell.startswith("#"):
                    continue
                try:
                    t = float(row[0])
                    v = float(row[1])
                except (ValueError, IndexError):
                    continue
                ts.append(t)
                vs.append(v)
    except OSError:
        return lambda t, _d=default: float(_d)
    if not ts:
        return lambda t, _d=default: float(_d)
    ts_a = np.asarray(ts, dtype=float)
    vs_a = np.asarray(vs, dtype=float) * float(scale)
    period = float(ts_a[-1] - ts_a[0])
    t0 = float(ts_a[0])

    def wf(t: float) -> float:
        tt = t
        if repeat and period > 0:
            tt = t0 + ((t - t0) % period)
        return float(np.interp(tt, ts_a, vs_a, left=vs_a[0], right=vs_a[-1]))

    return wf


def make_sine_waveform(v_rms: float, freq: float = 60.0,
                       phase_deg: float = 0.0,
                       offset: float = 0.0) -> Callable[[float], float]:
    """Build an instantaneous sine waveform for a time-domain V/I source.

    ``v_rms`` is the RMS amplitude — the peak is ``v_rms * sqrt(2)``.
    ``freq`` in Hz, ``phase_deg`` in degrees, ``offset`` is a constant
    DC bias (useful for biased AC sources). Returns ``f(t) -> float``.
    """
    v_peak = float(v_rms) * np.sqrt(2.0)
    omega = 2.0 * np.pi * float(freq)
    phi = np.deg2rad(float(phase_deg))
    bias = float(offset)

    def wf(t: float) -> float:
        return bias + v_peak * float(np.sin(omega * t + phi))
    return wf
