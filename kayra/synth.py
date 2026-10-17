"""Synthetic plants built from the real building, driven by hidden controllers.

SYNTHETIC. Labelled so everywhere it appears.

Each case: the real outdoor history (FMI Utti), the building model fitted to the
real fireplace room, the real clock, and a hidden controller deliberately
outside the seed catalogue. Noise is resampled from the real fit residuals,
then quantised to 0.1 °C like the real sensors.

The hypothesis loop never sees this file or the hidden expressions - it gets
only the simulated room series, exactly as it gets a real one. The checklist
per case (what counts as "right mechanism") is fixed here, before any run.

The parameter values below are arbitrary test values, chosen for plausibility.
They are not the real controller's settings and were not derived from the
Ouman readings or the sealed curve.
"""

from __future__ import annotations

import copy

import numpy as np
import torch

from . import dsl
from .load import Frame

# id -> hidden program, its values, and the mechanism checklist (operators/signals
# the recovered program must contain to count as the right mechanism).
HIDDEN = {
    "H1": {"what": "curve on 12-hour filtered outdoor, summer cutoff",
           "params": {"lv": "temp_c", "sl": "slope", "tau": "hours", "co": "temp_c"},
           "expr": "where(ema(T_out, tau) < co, lv + sl * ema(T_out, tau), OFF)",
           "values": {"lv": 44.0, "sl": -1.2, "tau": 12.0, "co": 15.0},
           "checklist": ["ema"]},
    "H2": {"what": "curve with weekday night setback",
           "params": {"lv": "temp_c", "sl": "slope", "dr": "delta_c", "on": "clock_h", "off": "clock_h", "wk": "clock_h"},
           "expr": "where(((hour_of_day() >= on) | (hour_of_day() < off)) & (weekday() < wk), lv - dr + sl * T_out, lv + sl * T_out)",
           "values": {"lv": 42.0, "sl": -1.0, "dr": 8.0, "on": 22.0, "off": 6.0, "wk": 4.5},
           "checklist": ["hour_of_day", "weekday"]},
    "H3": {"what": "PI on room temperature with output saturation",
           "params": {"kp": "gain", "sp": "temp_c", "ti": "hours", "mx": "temp_c"},
           "expr": "min(T_room + kp * (sp - T_room) + integral(sp - T_room, ti), mx)",
           "values": {"kp": 6.0, "sp": 21.5, "ti": 24.0, "mx": 38.0},
           "checklist": ["integral", "min|clip"]},
    "H4": {"what": "curve with cutoff hysteresis on outdoor",
           "params": {"lv": "temp_c", "sl": "slope", "lo": "temp_c", "hi": "temp_c"},
           "expr": "where(hysteresis(T_out, lo, hi), lv + sl * T_out, OFF)",
           "values": {"lv": 40.0, "sl": -1.1, "lo": 11.0, "hi": 16.0},
           "checklist": ["hysteresis"]},
    "H5": {"what": "STACK: weather curve plus a PI trim on the room that partly fights it",
           "params": {"lv": "temp_c", "sl": "slope", "kp": "gain", "sp": "temp_c", "ti": "hours"},
           "expr": "lv + sl * T_out + kp * (sp - T_room) + integral(sp - T_room, ti)",
           "values": {"lv": 36.0, "sl": -0.9, "kp": 2.0, "sp": 22.5, "ti": 48.0},
           "checklist": ["T_room", "integral"]},
    "H6": {"what": "STACK: weather curve gated by an on/off room thermostat",
           "params": {"lv": "temp_c", "sl": "slope", "lo": "temp_c", "hi": "temp_c"},
           "expr": "where(hysteresis(T_room, lo, hi), lv + sl * T_out, OFF)",
           "values": {"lv": 45.0, "sl": -1.3, "lo": 21.6, "hi": 22.4},
           "checklist": ["hysteresis", "T_room"]},
}


def simulate_full(f: Frame, building: dict, case: dict, T_start: float, seed: int, resid_sd: float) -> np.ndarray:
    """Run the hidden controller on the building over the whole outdoor history."""
    prog = dsl.validate({"id": "hidden", "params": case["params"], "expr": case["expr"]})
    t_out = np.nan_to_num(f.t_out, nan=float(np.nanmean(f.t_out)))
    inp = dsl.Inputs(t_out, f.hour_local, f.weekday_local, np.array([0]))
    theta = {k: torch.tensor([v]) for k, v in case["values"].items()}
    comp = dsl.Compiled(prog, theta)
    ctx = dsl.StepContext(inp)
    T = torch.tensor([[T_start]])
    comp.reset(1, 1, ctx.at(0, T))
    rng = np.random.default_rng(seed)
    a, h, g0, g1, phi = (building[k] for k in ("a", "h", "g0", "g1", "phi"))
    out = np.empty(len(t_out))
    out[0] = T_start
    for k in range(len(t_out) - 1):
        ctx.at(k, T)
        S = comp.fn(ctx).expand_as(T)
        heat = h * torch.clamp(S - T, min=0.0)
        T = T + a * (ctx.t_out_now - T) + heat + g0 + g1 * torch.cos(2 * np.pi * (ctx.hour_now - phi) / 24)
        T = T + float(rng.normal(0, resid_sd))  # process noise, scale from the real fit
        out[k + 1] = float(T)
    return np.round(out, 1)  # 0.1 °C quantisation, like the real sensors


def make_case(f: Frame, building: dict, case_id: str, resid_sd: float, seed: int = 0) -> Frame:
    """A Frame identical to the real one except the fireplace room is the synthetic plant."""
    g = copy.copy(f)
    T = simulate_full(f, building, HIDDEN[case_id], float(np.nanmedian(f.rooms["fireplace"])), seed, resid_sd)
    g.rooms = {"fireplace": T}
    g.humidity = {"fireplace": f.humidity["fireplace"]}
    g.sources = dict(f.sources, fireplace=f"SYNTHETIC {case_id}")
    return g


def right_mechanism(case_id: str, expr: str) -> bool:
    """Checklist fixed before the runs: every item (a|b = either) must appear in the program."""
    for item in HIDDEN[case_id]["checklist"]:
        if not any(alt in expr for alt in item.split("|")):
            return False
    return True
