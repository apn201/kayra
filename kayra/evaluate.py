"""Grade the identified curve against the configured one. THE ONLY FILE THAT OPENS THE SEALED CURVE.

    python -m kayra.evaluate

data/manual/ouman_curve_setting.csv is the answer key, read off the controller's
own menu by hand. No fitting code imports this module or reads that file - grep
the repo for the filename to check. The coding agent that wrote Käyrä never saw
its contents: this script was written without opening it, and was not run by
the agent.

Expected columns (case-insensitive, any order): one outdoor column (name contains
"out") and one L1 supply column (name contains "l1" or "supply"). Other columns
are ignored. Writes artifacts/eval.json; the panel overlays it on the Curve screen.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SEALED = ROOT / "data" / "manual" / "ouman_curve_setting.csv"
ART = ROOT / "artifacts"


def _num(s):
    try:
        return float(str(s).replace(",", "."))
    except ValueError:
        return None


def read_sealed() -> list[dict]:
    with open(SEALED, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit("ouman_curve_setting.csv has no rows yet - fill it from the curve photo first.")
    cols = list(rows[0])
    out_c = next((c for c in cols if "out" in c.lower()), None)
    sup_c = next((c for c in cols if "l1" in c.lower()), None) or next((c for c in cols if "supply" in c.lower()), None)
    if not out_c or not sup_c:
        raise SystemExit(f"Could not find outdoor and L1 supply columns in {cols}")
    pts = [{"outdoor_c": _num(r[out_c]), "supply_c": _num(r[sup_c])} for r in rows]
    return sorted([p for p in pts if p["outdoor_c"] is not None and p["supply_c"] is not None], key=lambda p: p["outdoor_c"])


def main() -> None:
    curve = read_sealed()
    real = json.loads((ART / "real.json").read_text(encoding="utf-8"))
    xs = np.array([p["outdoor_c"] for p in curve])
    ys = np.array([p["supply_c"] for p in curve])
    lo, hi = real["data"]["outdoor"]["min_c"], real["data"]["outdoor"]["max_c"]
    results = []
    for a in real["anchored_fireplace"]:
        b = a["band"]
        errs, inside = [], 0
        for g, p05, p50, p95 in zip(b["grid_c"], b["p05"], b["p50"], b["p95"]):
            if p50 is None or not (lo <= g <= hi) or g < xs.min() or g > xs.max():
                continue  # graded over the observed outdoor range only
            truth = float(np.interp(g, xs, ys))
            errs.append(p50 - truth)
            inside += int(p05 <= truth <= p95)
        results.append({"mode": a["mode"], "k": a["k"], "points": len(errs),
                        "rmse_c": round(float(np.sqrt(np.mean(np.square(errs)))), 2) if errs else None,
                        "bias_c": round(float(np.mean(errs)), 2) if errs else None,
                        "inside_band": inside})
    out = {"what": "identified fireplace-room equivalent curve vs configured L1 curve, observed outdoor range only",
           "note": "The room's equivalent curve is not L1 itself; FMI Utti reads 0.2-2.1 C cooler than the controller sensor.",
           "curve": curve, "results": results}
    ART.mkdir(exist_ok=True)
    (ART / "eval.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for r in results:
        print(r)


if __name__ == "__main__":
    main()
