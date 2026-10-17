"""Reference data: the Ouman panel readings. Graders and optional spot anchors, never product input.

Reads data/manual/ouman_readings.csv only. The configured curve
(ouman_curve_setting.csv) is sealed: only evaluate.py opens it.

Also here: the first lab-notebook entry - an operator's belief about the
controller ("L2 is L1 minus a few degrees"), tested against the panel's own
readings. Deterministic arithmetic; the language model only words it.
"""

from __future__ import annotations

import csv
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from .load import Frame, helsinki

ROOT = Path(__file__).resolve().parent.parent
READINGS = ROOT / "data" / "manual" / "ouman_readings.csv"
DISPLAY_SD = 0.5 / math.sqrt(3)   # integer display: uniform ±0.5 °C
OFFSET_SD = 1.0                   # controller sensor vs FMI Utti, carried as uncertainty


def _num(s):
    return float(s) if s not in ("", None) else None


def readings() -> list[dict]:
    rows = []
    with open(READINGS, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append({
                "timestamp_local": r["timestamp_local"], "time_known": r["time_known"] == "yes",
                "outdoor_controller_c": _num(r["outdoor_controller_c"]),
                "l1_supply_c": _num(r["l1_supply_c"]), "l1_setpoint_c": _num(r["l1_setpoint_c"]),
                "l2_supply_c": _num(r["l2_supply_c"]), "meter_mwh": _num(r["meter_mwh"]),
            })
    return rows


def to_utc(local: str) -> datetime:
    """Helsinki wall time to UTC (EEST +3 until 2026-10-25)."""
    t = datetime.fromisoformat(local).replace(tzinfo=timezone.utc)
    for off in (3, 2):
        u = t - timedelta(hours=off)
        if helsinki(u).replace(tzinfo=None) == t.replace(tzinfo=None):
            return u
    return t - timedelta(hours=3)


def anchors(k: int):
    """First k L1 readings in time order as spot anchors: (outdoor, supply, sigma) + the rest for scoring."""
    rows = [r for r in readings() if r["l1_supply_c"] is not None and r["outdoor_controller_c"] is not None]
    sigma = math.sqrt(DISPLAY_SD ** 2 + OFFSET_SD ** 2)
    use, rest = rows[:k], rows[k:]
    a = (np.array([r["outdoor_controller_c"] for r in use]), np.array([r["l1_supply_c"] for r in use]), sigma)
    return (a if k else None), rest


def controller_vs_fmi(f: Frame) -> list[dict]:
    out = []
    index = {t: i for i, t in enumerate(f.t)}
    for r in readings():
        if not r["time_known"]:
            continue
        u = to_utc(r["timestamp_local"])
        # nearest complete hour: the hour-start label of the hour ending closest to the reading
        hour = (u + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        i = index.get(hour)
        if i is None:
            continue
        out.append({"utc": u.isoformat(), "controller_c": r["outdoor_controller_c"],
                    "fmi_utti_c": float(f.t_out[i]), "offset_c": round(r["outdoor_controller_c"] - float(f.t_out[i]), 1)})
    return out


def operator_l2_belief() -> dict:
    """Operator belief: L2 = L1 minus a constant. Alternative: L2 = scaled L1 (own curve)."""
    rows = [r for r in readings() if r["l1_supply_c"] is not None and r["l2_supply_c"] is not None]
    l1 = np.array([r["l1_supply_c"] for r in rows])
    l2 = np.array([r["l2_supply_c"] for r in rows])
    out = np.array([r["outdoor_controller_c"] for r in rows])
    n = len(rows)
    gap = l1 - l2
    rms_const = float(np.sqrt(np.mean((gap - gap.mean()) ** 2)))
    A = np.c_[np.ones(n), l1]
    coef, *_ = np.linalg.lstsq(A, l2, rcond=None)
    rms_scaled = float(np.sqrt(np.mean((A @ coef - l2) ** 2)))
    noise = math.sqrt(2) * DISPLAY_SD  # difference of two rounded displays
    chi2_const = float(np.sum((gap - gap.mean()) ** 2) / noise ** 2)
    r_gap = float(np.corrcoef(gap, out)[0, 1])
    slope_gap = float(np.polyfit(out, gap, 1)[0])
    return {
        "id": "OP1", "source": "operator", "belief": "L2 is the same curve as L1 with a flat reduction",
        "readings": n, "gap_mean_c": round(float(gap.mean()), 2),
        "gap_vs_outdoor_corr": round(r_gap, 2), "gap_change_per_degree_colder_c": round(-slope_gap, 2),
        "rms_constant_offset_c": round(rms_const, 2), "rms_scaled_l1_c": round(rms_scaled, 2),
        "l2_per_l1_degree": round(float(coef[1]), 2),
        "rms_expected_from_rounding_c": round(noise, 2),
        "chi2_constant_offset": round(chi2_const, 1), "dof": n - 1,
        "verdict": ("refuted: the gap widens as it gets colder; L2 runs its own curve"
                    if rms_const > 2 * noise and rms_scaled < rms_const else "not refuted by the readings"),
    }


def operator_tv_people(f: Frame) -> dict:
    """Operator belief: the TV room warms on evenings from the people in it.
    Test: evening (18-23 local) temperature rise in the TV room against its neighbours,
    and whether humidity rises with it (people exhale water)."""
    tv, fp = f.rooms["tv"], f.rooms["fireplace"]
    h_tv = f.humidity["tv"]
    h = f.hour_local
    ev = []
    for i in range(1, len(f) - 6):
        if h[i] == 18 and not np.isnan(tv[i:i + 6]).any() and not np.isnan(fp[i:i + 6]).any():
            ev.append((tv[i + 5] - tv[i], fp[i + 5] - fp[i], h_tv[i + 5] - h_tv[i]))
    ev = np.array(ev)
    if not len(ev):
        return {"id": "OP2", "source": "operator", "verdict": "no evenings with data"}
    d_tv, d_fp, d_h = ev[:, 0], ev[:, 1], ev[:, 2]
    up = d_tv - d_fp > 0.2
    return {
        "id": "OP2", "source": "operator", "belief": "the TV room warms on evenings from the people in it",
        "evenings": int(len(ev)),
        "mean_tv_rise_18_23_c": round(float(d_tv.mean()), 3),
        "mean_neighbour_rise_18_23_c": round(float(d_fp.mean()), 3),
        "evenings_tv_outpaces_neighbour": int(up.sum()),
        "humidity_rise_on_those_evenings_pct": round(float(d_h[up].mean()), 2) if up.any() else None,
        "humidity_rise_other_evenings_pct": round(float(d_h[~up].mean()), 2) if (~up).any() else None,
        "verdict": ("supported: on the evenings the TV room outpaces its neighbour, its humidity rises more"
                    if up.any() and (~up).any() and d_h[up].mean() > d_h[~up].mean() + 0.3
                    else "not supported by the room data alone"),
    }
