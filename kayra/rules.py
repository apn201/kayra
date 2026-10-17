"""Named disturbance and drift rules over the hourly replay. Pattern after virta/scoring.py.

Deterministic, reviewed code. Thresholds are written here, in the open, not
fitted. Each finding carries the rule that fired and the numbers it came from.

residual = measured - predicted (the identified law's 1-24 h ahead prediction).
"""

from __future__ import annotations

import numpy as np

STEP_C = 0.3        # hourly temperature move that counts as a step
RH_STEP = 2.0       # hourly humidity move that counts as a step, % RH
FIRE_STEP_C = 0.5
DRIFT_C = 0.4       # mean residual across all rooms over DRIFT_H hours
DRIFT_H = 12
RH_FLAT = 3.0       # humidity range over the drift window that counts as "nothing in humidity"


def _d(rows, i, room, key):
    a, b = rows[i - 1][room].get(key), rows[i][room].get(key)
    return None if a is None or b is None else b - a


def scan(rows: list[dict], rooms: list[str]) -> list[dict]:
    out = []
    for i in range(1, len(rows)):
        t = rows[i]["t"]
        for room in rooms:
            dt, dh = _d(rows, i, room, "measured_c"), _d(rows, i, room, "rh")
            if dt is None or dh is None:
                continue
            if room == "fireplace" and dt >= FIRE_STEP_C and dh < 0:
                out.append({"t": t, "room": room, "rule": "fire", "kind": "disturbance (masked)",
                            "numbers": {"dT_c": round(dt, 2), "dRH": round(dh, 1)}})
            elif dt >= STEP_C and dh >= RH_STEP:
                hour = int(t[11:13])
                rule = "people" if room == "tv" and hour >= 15 else "cooking or shower"
                out.append({"t": t, "room": room, "rule": rule, "kind": "disturbance",
                            "numbers": {"dT_c": round(dt, 2), "dRH": round(dh, 1)}})
            elif dt <= -STEP_C and dh <= -RH_STEP:
                out.append({"t": t, "room": room, "rule": "window open", "kind": "disturbance",
                            "numbers": {"dT_c": round(dt, 2), "dRH": round(dh, 1)}})
    # drift: persistent residual in every room, nothing in humidity
    for i in range(DRIFT_H, len(rows), DRIFT_H // 2):
        seg = rows[i - DRIFT_H:i]
        res, rh_rng = [], []
        for room in rooms:
            r = [x[room]["measured_c"] - x[room]["predicted_c"] for x in seg
                 if x[room]["measured_c"] is not None and x[room]["predicted_c"] is not None]
            h = [x[room]["rh"] for x in seg if x[room]["rh"] is not None]
            if len(r) < DRIFT_H // 2 or len(h) < 2:
                break
            res.append(float(np.mean(r)))
            rh_rng.append(max(h) - min(h))
        else:
            same_sign = all(x < -DRIFT_C for x in res) or all(x > DRIFT_C for x in res)
            if same_sign and max(rh_rng) < RH_FLAT:
                out.append({"t": seg[-1]["t"], "room": "all", "rule": "drift", "kind": "ALERT",
                            "numbers": {"mean_residual_c": {r: round(x, 2) for r, x in zip(rooms, res)},
                                        "rh_range": {r: round(x, 1) for r, x in zip(rooms, rh_rng)},
                                        "hours": DRIFT_H}})
    return out
