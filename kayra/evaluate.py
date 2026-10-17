"""Grade the identified curves against the configured ones. THE ONLY FILE THAT OPENS THE SEALED CURVE.

    python -m kayra.evaluate

data/manual/ouman_curve_setting.csv is the answer key, read off the controller's own menu by hand:
    outdoor_c,supply_c,note        note = the loop, L1 or L2; three points per loop (-20, 0, +20)
No fitting code imports this module or reads that file. In the git history it arrives in the commit
after all fits were made. The coding agent never opened it and reads only the error numbers this
script prints - never the curve values.

Three questions, all answered with error numbers only:
 1. Label check: does each sealed loop curve agree with the panel's own supply readings of that loop?
 2. Which room group runs on which loop? The identified curve of each room group (site.json loops)
    is compared with each sealed loop. Slope is what room data can identify, so slope decides;
    level is reported but HA-only level is known to be loose.
 3. How far off is each identified curve, HA-only and with spot readings, over the observed range?

Writes artifacts/eval.json; the panel overlays the configured curves only after this has run.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from . import reference

ROOT = Path(__file__).resolve().parent.parent
SEALED = ROOT / "data" / "manual" / "ouman_curve_setting.csv"
ART = ROOT / "artifacts"


def _num(s):
    try:
        return float(str(s).replace(",", "."))
    except ValueError:
        return None


def read_sealed() -> dict[str, list[tuple[float, float]]]:
    with open(SEALED, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    loops: dict[str, list] = {}
    for r in rows:
        x, y = _num(r.get("outdoor_c")), _num(r.get("supply_c"))
        loop = (r.get("note") or "").strip().upper()
        if x is None or y is None or not loop:
            continue
        loops.setdefault(loop, []).append((x, y))
    if not loops:
        raise SystemExit("ouman_curve_setting.csv: no rows with numeric outdoor_c, supply_c and a loop in note.")
    return {k: sorted(v) for k, v in loops.items()}


def at(curve, x):
    xs, ys = zip(*curve)
    return float(np.interp(x, xs, ys))


def slope(curve, lo, hi):
    return (at(curve, hi) - at(curve, lo)) / (hi - lo)


def main() -> None:
    sealed = read_sealed()
    real = json.loads((ART / "real.json").read_text(encoding="utf-8"))
    out_lo = max(real["data"]["outdoor"]["min_c"], -20.0)
    rd = [r for r in reference.readings() if r["outdoor_controller_c"] is not None]

    # 1. label check against the panel's own readings
    labels = {}
    for loop, curve in sealed.items():
        for panel_key in ("l1_supply_c", "l2_supply_c"):
            pts = [(r["outdoor_controller_c"], r[panel_key]) for r in rd if r[panel_key] is not None]
            err = [at(curve, x) - y for x, y in pts]
            labels[f"sealed {loop} vs panel {panel_key[:2].upper()} readings"] = {
                "rmse_c": round(float(np.sqrt(np.mean(np.square(err)))), 2), "n": len(err)}

    # 2. which room group runs on which loop: compare identified slopes over the heating range
    simple = real.get("simple") or {}
    groups = {lid: s for lid, s in simple.items()}
    lo, hi = out_lo, 15.0
    assign = {}
    for gid, g in groups.items():
        th = g["theta"]
        for loop, curve in sealed.items():
            s_id, s_cfg = th["slope"], slope(curve, lo, hi)
            lvl = [th["level"] + th["slope"] * x - at(curve, x) for x in np.linspace(lo, hi, 9)]
            assign[f"rooms {'+'.join(g['rooms'])} vs sealed {loop}"] = {
                "slope_error_c_per_c": round(s_id - s_cfg, 2),
                "level_rmse_c": round(float(np.sqrt(np.mean(np.square(lvl)))), 2)}
    gids, loops = list(groups), sorted(sealed)
    verdict = None
    if len(gids) == 2 and len(loops) == 2:
        def cost(pairs):
            return sum(abs(assign[f"rooms {'+'.join(groups[g]['rooms'])} vs sealed {l}"]["slope_error_c_per_c"]) for g, l in pairs)
        a = list(zip(gids, loops))
        b = list(zip(gids, reversed(loops)))
        best, other = (a, b) if cost(a) <= cost(b) else (b, a)
        verdict = {"by_slope": {groups[g]["name"] + " (" + "+".join(groups[g]["rooms"]) + ")": l for g, l in best},
                   "slope_error_sum_best": round(cost(best), 2), "slope_error_sum_other": round(cost(other), 2),
                   "margin_c_per_c": round(cost(other) - cost(best), 2)}

    # 3. anchored fireplace curves (anchors = panel L1 readings) against each sealed loop
    anchored = []
    for a in real["anchored_fireplace"]:
        b = a["band"]
        row = {"mode": a["mode"], "k": a["k"]}
        for loop, curve in sealed.items():
            errs, inside = [], 0
            for g, p05, p50, p95 in zip(b["grid_c"], b["p05"], b["p50"], b["p95"]):
                if p50 is None or not (out_lo <= g <= 15):
                    continue
                t = at(curve, g)
                errs.append(p50 - t)
                inside += int(p05 <= t <= p95)
            row[f"rmse_vs_{loop}_c"] = round(float(np.sqrt(np.mean(np.square(errs)))), 2) if errs else None
            row[f"inside_band_{loop}"] = f"{inside}/{len(errs)}"
        anchored.append(row)

    out = {"what": "identified curves vs configured curves, observed outdoor range only",
           "notes": ["HA-only level is loose by design; slope is the identifiable part.",
                     "FMI Utti reads 0.2-1.1 C cooler than the controller's own sensor in six checks; not corrected.",
                     "The fireplace-room curve is that room's equivalent curve, not a loop curve."],
           "label_check": labels, "assignment": assign, "assignment_verdict": verdict, "anchored": anchored,
           "curves": {k: [{"outdoor_c": x, "supply_c": y} for x, y in v] for k, v in sealed.items()}}
    ART.mkdir(exist_ok=True)
    (ART / "eval.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    # print error numbers only - never the curve values
    print(json.dumps({k: out[k] for k in ("label_check", "assignment", "assignment_verdict", "anchored")}, indent=1))


if __name__ == "__main__":
    main()
