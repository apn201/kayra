"""The document the plant never had: as-found specification, notebook, limits.

Built from artifacts/*.json by fixed templates. Every number in it is read from
an artifact; none is typed here. When a language model is online it may reword
sections, and every reworded line goes through guardrails.ungrounded_numbers
against the artifact it came from - a line with an invented number is dropped.
While the model is offline the template text ships as is, and says so.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts"
ROOM_NAMES = {"kitchen": "Kitchen (upstairs, floor heating)", "fireplace": "Fireplace room (downstairs, radiators)",
              "tv": "TV room (downstairs, radiator with thermostatic valve almost closed)"}


def _load(name):
    p = ART / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _curve_table(band) -> list[str]:
    lines = ["| Outdoor °C | Supply p05 | p50 | p95 | heat on |", "|---|---|---|---|---|"]
    for i, g in enumerate(band["grid_c"]):
        p = [band[q][i] for q in ("p05", "p50", "p95")]
        cells = ["-" if v is None else f"{v:.1f}" for v in p]
        lines.append(f"| {g} | {cells[0]} | {cells[1]} | {cells[2]} | {band['heat_on_share'][i]:.0%} |")
    return lines


def build() -> str:
    real, syn, bench = _load("real.json"), _load("synth.json"), _load("benchmark.json")
    L = ["# As-found specification - heating controller stack", ""]
    if real:
        m = real["meta"]
        L += [f"Generated {m['generated_utc']} on `{m['device']['device']}` (torch {m['device']['torch']}). "
              f"Language model: **{m['llm']}**.", ""]
        if "OFFLINE" in m["llm"]:
            L += ["> The language model was unavailable for this run. Hypotheses marked *stand-in (hand-written)* "
                  "were written by the developer, not by a model. Prose in this document is template text. "
                  "Every number was computed by the fitter.", ""]
        d = real["data"]
        o = d["outdoor"]
        L += ["## Data", "",
              f"- Outdoor: {o['station']}, {o['hours']} hours, {o['first'][:10]} to {o['last'][:10]}, "
              f"{o['min_c']} to {o['max_c']} °C, {o['interpolated_hours']} hours interpolated.",
              ]
        for r, s in d["rooms"].items():
            L.append(f"- {ROOM_NAMES.get(r, r)}: {s.get('hours')} hourly means, {s.get('first', '')[:10]} to "
                     f"{s.get('last', '')[:10]} (`{s.get('file')}`).")
        L += ["", "Room data end where the last Home Assistant pull ends. Outdoor runs to the time of the run.", ""]

        L += ["## What is in the box, per room", ""]
        for room, R in real["rooms"].items():
            top = R["ranked"][:4]
            L += [f"### {ROOM_NAMES.get(room, room)}", "",
                  f"Scored on {R['windows_cold']} cold windows (mean outdoor under 12 °C), "
                  f"{R['windows_held_out']} held out. Building loss time constant from the summer free-float: "
                  f"{R['summer_prior']['time_constant_h']} h over {R['summer_prior']['windows']} warm windows.", "",
                  "| Rank | Program | Source | Held-out RMSE °C | ΔBIC | P |", "|---|---|---|---|---|---|"]
            for i, x in enumerate(top, 1):
                L.append(f"| {i} | {x['id']} {x['name']} | {x['source']} | {x['rmse_held_c']} | {x['delta_bic']} | {x['prob']:.2f} |")
            ties = [x["id"] for x in R["ranked"] if x.get("tie_with_best")]
            L += ["", f"Best: `{R['best']['expr']}`." + (f" Tie with {', '.join(ties)} - the data do not separate them." if ties else ""), ""]
        loops = {k: v for k, v in (real.get("loops") or {}).items() if v.get("ranked")}
        if loops:
            L += ["## Heating loops (operator site knowledge)", "",
                  "Rooms on one loop share one controller program; each room keeps its own building parameters.", ""]
            for lid, Lp in loops.items():
                b = Lp["ranked"][0]
                L += [f"### {lid} {Lp['name']}: {', '.join(Lp['rooms'])}", "", f"Operator: {Lp['operator_notes']}", "",
                      f"Best: {b['id']} {b['name']} (`{Lp['best']['expr']}`), held-out RMSE {b['rmse_held_c']} °C, "
                      f"ΔBIC to runner-up {Lp['ranked'][1]['delta_bic']}.", "",
                      "| Room | Heating share | RMSE in loop °C | RMSE fitted alone °C |", "|---|---|---|---|"]
                for r in Lp["rooms"]:
                    L.append(f"| {r} | {Lp['heating_share'][r]:.0%} | {Lp['held_rmse_rooms'][r]} | {Lp['held_rmse_rooms_fitted_alone'][r]} |")
                L.append("")
        L += ["## Equivalent curve, fireplace room", "",
              "HA-only, then anchored with k panel readings of L1. Band = likelihood-weighted 5-95 % of the "
              "search population. Curve is identified over the observed outdoor range only.", ""]
        for a in real["anchored_fireplace"]:
            L.append(f"- {a['mode']}: RMSE against the remaining {a['scored_on']} panel readings "
                     f"{a['rmse_vs_panel_l1_c']} °C, band width at 4 °C outdoor {a['band_width_at_4c']} °C.")
        L += [""] + _curve_table(real["rooms"]["fireplace"]["curve"]["band"]) + [""]

        L += ["## Operator beliefs, tested", ""]
        for op in real["operator"]:
            L.append(f"- **{op['id']}** \"{op.get('belief', '')}\" - {op['verdict']}.")
            L.append("  " + ", ".join(f"{k} {v}" for k, v in op.items() if k not in ("id", "source", "belief", "verdict")))
        L += ["", "## Controller outdoor sensor vs FMI Utti", ""]
        for c in real["controller_vs_fmi"]:
            L.append(f"- {c['utc'][:16]}Z controller {c['controller_c']} °C, Utti {c['fmi_utti_c']} °C, offset {c['offset_c']:+}")
        L += ["", "Carried as uncertainty, not as a correction.", ""]
        al = [a for a in real["alerts"] if a["kind"] == "ALERT"]
        L += ["## Alerts in the replay window", "",
              f"{len(al)} drift alerts, {len(real['alerts']) - len(al)} disturbances explained by named rules.", ""]
    if syn:
        L += ["## Synthetic benchmark (SYNTHETIC)", "", syn["label"] + ".", "",
              "| Case | Hidden | Arm A best | right? | Arm B best | right? | Arm C |", "|---|---|---|---|---|---|---|"]
        for c in syn["cases"]:
            A, B, C = c["arms"]["A"], c["arms"]["B"], c["arms"]["C"]
            cc = C.get("status", f"{C.get('best')} {'yes' if C.get('right_mechanism') else 'no'}")
            L.append(f"| {c['id']} | {c['hidden']} | {A['best']} ({A['rmse_held_c']}) | {'yes' if A['right_mechanism'] else 'no'} "
                     f"| {B['best']} ({B['rmse_held_c']}) | {'yes' if B['right_mechanism'] else 'no'} | {cc[:40]} |")
        L.append("")
    if bench:
        L += ["## Compute", ""]
        for r in bench["runs"]:
            L.append(f"- {r['device']} x{r['threads']} threads: {r['candidates']} candidates in {r['wall_s']} s, "
                     f"{r['room_hours_simulated_per_s']} room-hours simulated per second.")
        if bench.get("gpu"):
            L.append(f"- AMD GPU: {bench['gpu']['status']}")
        L.append("")
    L += ["## Not done in this version", "",
          "- Replacement specification (tiers 0-3): not run. Screen shows PENDING.",
          "- Room coupling in the process map: not fitted; rooms are identified independently.",
          "- Live posterior from the house pusher: the panel replays recorded history.", "",
          "## Limits", "",
          "- Structure discovery is demonstrated on synthetic cases built from the real building; on the real stack it is one data point.",
          "- From Home Assistant alone the curve's slope is identifiable, its level only loosely.",
          "- Winter is unobserved; no extrapolation below the observed outdoor range.",
          "- The two heating loops share one input; from room data they are one equivalent curve per room.",
          "- Validated in simulation only. Nothing was written to the controller.", ""]
    text = "\n".join(L)
    ART.mkdir(exist_ok=True)
    (ART / "document.md").write_text(text, encoding="utf-8")
    print("wrote artifacts/document.md")
    return text


if __name__ == "__main__":
    build()
