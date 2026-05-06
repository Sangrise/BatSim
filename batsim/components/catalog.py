"""Component catalog used by the UI palette and the netlist builder.

Each entry describes:
  - kind: engine kind string (R, L, C, V, I, BATTERY, SWITCH, GND)
  - label: human-readable
  - pins: number of terminals
  - default_params: parameter defaults
  - symbol: simple drawing primitives (lines, circles, text) in local coords
            ((-30..30, -30..30) bounding box; pins at (-30,0) and (30,0) for 2-pin)
"""
from __future__ import annotations

CATALOG: dict[str, dict] = {
    "R": {
        "label": "Resistor",
        "kind": "R",
        "pins": 2,
        "default_params": {"R": 1000.0},
        "symbol": [
            ("line", -30, 0, -15, 0),
            ("rect", -15, -6, 30, 12),
            ("line", 15, 0, 30, 0),
            ("text", 0, -16, "R"),
        ],
    },
    "L": {
        "label": "Inductor",
        "kind": "L",
        "pins": 2,
        "default_params": {"L": 1e-3},
        "symbol": [
            ("line", -30, 0, -15, 0),
            ("arc", -15, -8, 10, 16, 0, 180),
            ("arc", -5, -8, 10, 16, 0, 180),
            ("arc", 5, -8, 10, 16, 0, 180),
            ("line", 15, 0, 30, 0),
            ("text", 0, -16, "L"),
        ],
    },
    "C": {
        "label": "Capacitor",
        "kind": "C",
        "pins": 2,
        "default_params": {"C": 1e-6},
        "symbol": [
            ("line", -30, 0, -3, 0),
            ("line", -3, -10, -3, 10),
            ("line", 3, -10, 3, 10),
            ("line", 3, 0, 30, 0),
            ("text", 0, -16, "C"),
        ],
    },
    "V": {
        "label": "Voltage source",
        "kind": "V",
        "pins": 2,
        "default_params": {"V": 5.0},
        "symbol": [
            ("line", -30, 0, -12, 0),
            ("circle", 0, 0, 12),
            ("text", -4, 4, "+"),
            ("text", 5, 4, "-"),
            ("line", 12, 0, 30, 0),
            ("text", 0, -18, "V"),
        ],
    },
    "I": {
        "label": "Current source",
        "kind": "I",
        "pins": 2,
        "default_params": {"I": 0.1},
        "symbol": [
            ("line", -30, 0, -12, 0),
            ("circle", 0, 0, 12),
            ("text", -3, 4, "↑"),
            ("line", 12, 0, 30, 0),
            ("text", 0, -18, "I"),
        ],
    },
    "SWITCH": {
        "label": "Switch",
        "kind": "SWITCH",
        "pins": 2,
        "default_params": {"closed": True},
        "symbol": [
            ("line", -30, 0, -10, 0),
            ("line", -10, 0, 8, -10),
            ("line", 10, 0, 30, 0),
            ("text", 0, -18, "SW"),
        ],
    },
    "BATTERY": {
        "label": "Battery cell",
        "kind": "BATTERY",
        "pins": 2,
        "default_params": {
            "model": "Thevenin",
            "cell": "",
            "capacity_Ah": 2.5,
            "soc0": 1.0,
            "R0": 0.03,
            "R1": 0.02,
            "C1": 2000.0,
        },
        "symbol": [
            ("line", -30, 0, -8, 0),
            ("line", -8, -12, -8, 12),
            ("line", -3, -6, -3, 6),
            ("line", 3, -10, 3, 10),
            ("line", 8, -6, 8, 6),
            ("line", 8, 0, 30, 0),
            ("text", -16, -14, "+"),
            ("text", 12, -14, "-"),
            ("text", 0, 22, "BAT"),
        ],
    },
    "BATPACK": {
        "label": "Battery pack (series/parallel)",
        "kind": "BATPACK",
        "pins": 2,
        "default_params": {
            "model": "Thevenin",
            "cell": "",
            "n_series": 4,
            "n_parallel": 1,
            "capacity_Ah": 2.5,
            "soc0": 1.0,
            "soc_init_spread": 0.04,
            "R0": 0.03,
            "R1": 0.02,
            "C1": 2000.0,
            "balancer": "PassiveV1",
            "balancer_soc_enable": 0.46,
            "balancer_dev_min":    0.02,
            "balancer_dev_max":    1.0,
            "balancer_soc_drop":   0.001,
            "balancer_I_bal":      1.0,
            "balancer_pack_pause": 0.05,
            "balancer_pack_resume":0.08,
        },
        "symbol": [
            ("line", -30, 0, -14, 0),
            ("line", -14, -14, -14, 14),
            ("line", -10, -8, -10, 8),
            ("line", -4, -14, -4, 14),
            ("line",  0, -8,  0, 8),
            ("line",  6, -14,  6, 14),
            ("line", 10, -8, 10, 8),
            ("line", 14, -14, 14, 14),
            ("line", 14, 0, 30, 0),
            ("text", -22, -18, "+"),
            ("text", 18, -18, "-"),
            ("text", 0, 24, "PACK"),
        ],
    },
    "BATRACK": {
        "label": "Battery rack (packs in series)",
        "kind": "BATRACK",
        "pins": 2,
        "default_params": {
            "model": "Thevenin",
            "cell": "",
            "n_packs_series": 4,    # number of BATPACKs stacked in series
            "n_series": 4,          # cells in series per pack
            "n_parallel": 1,        # parallel strings per pack
            "capacity_Ah": 2.5,
            "soc0": 1.0,
            "soc_init_spread": 0.04,
            "R0": 0.03,
            "R1": 0.02,
            "C1": 2000.0,
            # Per-pack balancer (used unless a BMS component overrides it).
            "balancer": "PassiveV1",
            "balancer_soc_enable": 0.46,
            "balancer_dev_min":    0.02,
            "balancer_dev_max":    1.0,
            "balancer_soc_drop":   0.001,
            "balancer_I_bal":      1.0,
            "balancer_pack_pause": 0.05,
            "balancer_pack_resume":0.08,
        },
        "symbol": [
            ("line", -30, 0, -22, 0),
            ("rect", -22, -16, 12, 32),
            ("rect", -18, -12, 4, 8),
            ("rect", -18, 4, 4, 8),
            ("rect", -12, -12, 4, 8),
            ("rect", -12, 4, 4, 8),
            ("rect", -6, -12, 4, 8),
            ("rect", -6, 4, 4, 8),
            ("line", -10, 0, 22, 0),
            ("text", -28, -22, "+"),
            ("text", 18, -22, "-"),
            ("text", 0, 26, "RACK"),
        ],
    },
    "BMS": {
        "label": "Battery Management System",
        "kind": "BMS",
        "pins": 0,
        # BMS is a virtual component (no electrical pins).  It declares
        # which battery components are inside its control domain via the
        # `targets` parameter (comma-separated component IDs, e.g.
        # "BR1,BR2") and what balancer logic to push into them.  Use one
        # BMS per group of batteries; multiple BMSes can coexist with
        # disjoint target sets.
        "default_params": {
            "targets": "",                       # comma-separated battery IDs
            "balancer": "Inherit",               # "Inherit" = leave per-pack default
            "balancer_soc_enable": 0.46,
            "balancer_dev_min":    0.02,
            "balancer_dev_max":    1.0,
            "balancer_soc_drop":   0.001,
            "balancer_I_bal":      1.0,
            "balancer_pack_pause": 0.05,
            "balancer_pack_resume":0.08,
        },
        "symbol": [
            ("rect", -30, -16, 60, 32),
            ("text", 0, -2, "BMS"),
            ("text", 0, 12, "(controller)"),
        ],
    },
    "GND": {
        "label": "Ground",
        "kind": "GND",
        "pins": 1,
        "default_params": {},
        "symbol": [
            ("line", 0, -10, 0, 0),
            ("line", -12, 0, 12, 0),
            ("line", -8, 5, 8, 5),
            ("line", -4, 10, 4, 10),
        ],
    },
    "DIODE": {
        "label": "Diode",
        "kind": "DIODE",
        "pins": 2,
        "default_params": {"Is": 1e-12, "n": 1.0, "Vt": 0.02585},
        "symbol": [
            ("line", -30, 0, -10, 0),
            ("line", -10, -8, -10, 8),
            ("line", -10, -8, 10, 0),
            ("line", -10, 8, 10, 0),
            ("line", 10, -8, 10, 8),
            ("line", 10, 0, 30, 0),
            ("text", 0, -16, "D"),
        ],
    },
    "MOSFET": {
        "label": "MOSFET (NMOS)",
        "kind": "MOSFET",
        "pins": 3,
        "default_params": {"Kp": 2e-4, "Vth": 1.0, "lambda": 0.0},
        "symbol": [
            ("line", -30, 0, -8, 0),
            ("line", -8, -12, -8, 12),
            ("line", 0, -12, 0, -4),
            ("line", 0, 4, 0, 12),
            ("line", 0, -8, 12, -8),
            ("line", 0, 8, 12, 8),
            ("line", 12, -20, 12, -8),
            ("line", 12, 8, 12, 20),
            ("text", 0, 28, "MOS"),
        ],
    },
    "PROBE": {
        "label": "Voltage probe (differential)",
        "kind": "PROBE",
        "pins": 2,
        "default_params": {},
        "symbol": [
            ("line", -30, 0, -10, 0),
            ("line", 10, 0, 30, 0),
            ("rect", -10, -8, 20, 16),
            ("text", 0, 4, "V"),
            ("text", -22, -10, "+"),
            ("text", 18, -10, "−"),
            ("text", 0, -16, "Vp"),
        ],
    },
    "IPROBE": {
        "label": "Current probe (drop on a wire)",
        "kind": "IPROBE",
        "pins": 2,
        "default_params": {},
        # Visual: a small clamp ring centred on the wire.  The two engine
        # pins are at (-12, 0) and (12, 0) so the auto-split wires meet
        # the ring's edges; the ring itself reads as a single point.
        "symbol": [
            ("circle", 0, 0, 9),
            ("circle", 0, 0, 5),
            ("text", 0, 4, "A"),
            ("text", 0, -16, "I"),
        ],
    },
    "IPATTERN": {
        "label": "Pattern current source (CSV)",
        "kind": "IPATTERN",
        "pins": 2,
        "default_params": {"csv": "", "scale": 1.0, "repeat": True, "I": 0.0},
        "symbol": [
            ("line", -30, 0, -12, 0),
            ("circle", 0, 0, 12),
            ("text", -7, 4, "~I"),
            ("line", 12, 0, 30, 0),
            ("text", 0, -18, "Ipat"),
        ],
    },
    "ICONST": {
        "label": "Constant current load",
        "kind": "ICONST",
        "pins": 2,
        "default_params": {"I": 1.0},  # positive = current flows pin0 -> pin1
        "symbol": [
            ("line", -30, 0, -12, 0),
            ("circle", 0, 0, 12),
            ("text", -3, 4, "↑"),
            ("line", 12, 0, 30, 0),
            ("text", 0, -18, "Icst"),
        ],
    },
    "PCONST": {
        "label": "Constant power load",
        "kind": "PCONST",
        "pins": 2,
        "default_params": {"P": 10.0},  # positive = sink (load on +pin)
        "symbol": [
            ("line", -30, 0, -12, 0),
            ("circle", 0, 0, 12),
            ("text", -4, 4, "P"),
            ("line", 12, 0, 30, 0),
            ("text", 0, -18, "Pcst"),
        ],
    },
    "JUNCTION": {
        "label": "Junction (T-tap)",
        "kind": "JUNCTION",
        "pins": 1,
        "default_params": {},
        "symbol": [("fcircle", 0, 0, 4)],
    },
    "BUS": {
        "label": "Grid / Load bus",
        "kind": "BUS",
        "pins": 2,
        # mode = Grid | PLoad | ILoad.  Pin 0 is the "+" / hot terminal,
        # pin 1 is the "-" / return terminal which is internally referenced
        # to node 0 (the bus owns the system ground reference).
        "default_params": {
            "mode": "Grid",
            "V": 400.0,    # used in Grid mode (open-circuit voltage)
            "P": 1000.0,   # used in PLoad mode (W; +ve = sinks power)
            "I": 10.0,     # used in ILoad mode (A; +ve = pin0 -> pin1)
        },
        "symbol": [
            ("line", -30, 0, -10, 0),
            ("rect", -10, -14, 20, 28),
            ("text", 0, -2, "BUS"),
            ("text", -8, 12, "+"),
            ("text", 4, 12, "-"),
            ("line", 10, 0, 30, 0),
            ("text", 0, 22, "Grid/Load"),
        ],
    },
    "TR": {
        "label": "Ideal transformer (AC turns-ratio coupler)",
        "kind": "TR",
        "pins": 4,
        # n = primary / secondary turns ratio (Vp = n * Vs, Is = -n * Ip).
        # Works for both AC time-domain and DC; in BatSim's time-domain
        # engine an "AC transformer" is the same equation evaluated at
        # every step on a sinusoidal source.
        "default_params": {"n": 10.0},
        "symbol": [
            ("line", -30, -16, -12, -16),
            ("line", -30, 16, -12, 16),
            ("arc", -14, -22, 6, 12, 90, 180),
            ("arc", -14, -10, 6, 12, 90, 180),
            ("arc", -14, 4, 6, 12, 90, 180),
            ("line", -2, -22, -2, 22),
            ("line", 2, -22, 2, 22),
            ("arc", 8, -22, 6, 12, -90, 180),
            ("arc", 8, -10, 6, 12, -90, 180),
            ("arc", 8, 4, 6, 12, -90, 180),
            ("line", 12, -16, 30, -16),
            ("line", 12, 16, 30, 16),
            ("text", 0, 32, "TR (AC)"),
        ],
    },
    "GRID": {
        "label": "AC grid source",
        "kind": "GRID",
        "pins": 2,
        # Sinusoidal voltage source.  Pin 0 = line, pin 1 = neutral
        # (auto-anchored to node 0).  V_rms is RMS line-to-neutral.
        "default_params": {
            "V_rms": 220.0,
            "freq": 60.0,
            "phase_deg": 0.0,
        },
        "symbol": [
            ("line", -30, 0, -12, 0),
            ("circle", 0, 0, 12),
            ("text", -7, 4, "~"),
            ("line", 12, 0, 30, 0),
            ("text", 0, -18, "GRID"),
            ("text", 0, 22, "AC"),
        ],
    },
    "PCS": {
        "label": "Power Conversion System (AC↔DC)",
        "kind": "PCS",
        "pins": 4,
        # Pins: [AC+, AC-, DC+, DC-].  AC- and DC- both auto-anchored
        # to node 0 (single-reference engine; galvanic isolation is not
        # modelled in v1).
        # Modes:
        #   V_DC  — regulate DC bus to V_DC_set (most common).
        #   I_DC  — inject constant DC current I_DC_set.
        #   P_DC  — exchange constant DC power P_DC_set.
        # AC side draws/supplies the matching instantaneous power
        # (linearised by Newton).  ``eta`` is round-trip efficiency.
        # Profiles (mode):
        #   V_DC / I_DC / P_DC — legacy stiff setpoints.
        #   CC                  — constant current (I_set; +charge/−discharge).
        #   CV                  — constant voltage (V_set).
        #   CP                  — constant power  (P_set; +charge/−discharge).
        #   CCCV                — CC until V≥V_max → CV until |I|≤I_term.
        #   CPCV                — CP until V≥V_max → CV until |I|≤I_term.
        #   CYCLE               — execute cycle_steps (JSON list) cycle_repeat
        #                         times.  Each step: {mode, I/V/P, V_max/V_min,
        #                         I_term, max_time, time}.
        # Modes (high-level; CYCLE_SIMPLE is the recommended default for
        # cycle testing, others are advanced):
        #   V_DC / I_DC / P_DC — stiff DC setpoint.
        #   CC / CV / CP        — single-phase profile.
        #   CCCV / CPCV         — single charge OR discharge with CV taper.
        #   CYCLE_SIMPLE        — repeating charge(CCCV)→rest→discharge(CC)→
        #                         rest cycle.  Only 7 numeric params, no JSON.
        #   CYCLE               — advanced: arbitrary step list (cycle_steps
        #                         JSON).  Use only if CYCLE_SIMPLE isn't
        #                         enough.
        "default_params": {
            "mode": "V_DC",
            "n_series": 1,
            "V_DC_set": 800.0,
            "I_DC_set": 0.0,
            "P_DC_set": 0.0,
            "I_set": 0.0,
            "V_set": 0.0,
            "P_set": 0.0,
            "V_max": 0.0,
            "V_min": 0.0,
            "I_term": 0.0,
            # CYCLE_SIMPLE parameters
            "cyc_I_chg": 0.0,
            "cyc_I_dis": 0.0,
            "cyc_V_max": 4.2,
            "cyc_V_min": 3.0,
            "cyc_t_rest": 600.0,
            "cyc_count": 1,
            # CYCLE (advanced) parameters
            "cycle_steps": "[]",
            "cycle_repeat": 1,
            "eta": 0.98,
        },
        "symbol": [
            ("line", -30, -16, -10, -16),
            ("line", -30, 16, -10, 16),
            ("rect", -10, -22, 20, 44),
            ("text", 0, -2, "PCS"),
            ("text", -7, -16, "~"),
            ("text", -7, 16, "~"),
            ("text", 5, -16, "="),
            ("text", 5, 16, "="),
            ("line", 10, -16, 30, -16),
            ("line", 10, 16, 30, 16),
            ("text", 0, 32, "AC↔DC"),
        ],
    },
}


def pin_offsets(kind: str) -> list[tuple[float, float]]:
    """Local pin coordinates for each component kind."""
    n = CATALOG[kind]["pins"]
    if n == 1:
        if kind == "PROBE":
            return [(0.0, -20.0)]  # legacy single-pin probe
        if kind in ("JUNCTION", "IPROBE"):
            return [(0.0, 0.0)]
        return [(0.0, -10.0)]
    if n == 2 and kind == "IPROBE":
        # Clamp probe: pins on the ring's edges (±12) so the auto-split
        # wires meet the small ring symbol cleanly without sticking out.
        return [(-12.0, 0.0), (12.0, 0.0)]
    if n == 2 and kind == "PROBE":
        # Differential probe: V(+) on left, V(−) on right
        return [(-30.0, 0.0), (30.0, 0.0)]
    if n == 3 and kind == "MOSFET":
        # D (top), G (left), S (bottom)
        return [(12.0, -20.0), (-30.0, 0.0), (12.0, 20.0)]
    if n == 4 and kind == "TR":
        # primary +, primary -, secondary +, secondary -
        return [(-30.0, -16.0), (-30.0, 16.0), (30.0, -16.0), (30.0, 16.0)]
    if n == 4 and kind == "PCS":
        # AC+ (top-left), AC- (bottom-left), DC+ (top-right), DC- (bottom-right)
        return [(-30.0, -16.0), (-30.0, 16.0), (30.0, -16.0), (30.0, 16.0)]
    return [(-30.0, 0.0), (30.0, 0.0)]
