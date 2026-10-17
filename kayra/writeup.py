"""The as-found specification, written by the model from the computed evidence.

    python -m kayra.writeup        reads artifacts/real.json (+ context.json, synth.json), writes artifacts/writeup.json

The engineer who inherits the loop reads this, not JSON. The model writes it; every line goes
through guardrails.ungrounded_numbers against the evidence packet, and a line with a number that is
not in the packet is dropped and listed. Reasoning is not checked by code, so the panel shows the
computed tables next to it. The operator summary is also written in Finnish, for the technician on site.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import client, guardrails

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts"

SYSTEM = (
    "You write the as-found specification for an undocumented heating controller stack, for the maintenance "
    "engineer who inherited it. Plain operator language, short sentences, no hype, no marketing. You get an "
    "evidence packet computed by a fitter. Every number you write must appear in the packet, copied exactly, "
    "and you must say what it measures. Never round, convert or combine numbers. Say plainly what the data "
    "could not tell. Never claim the controller was changed or tested on the building: everything is from "
    "logged data and simulation. Return ONLY JSON."
)

SECTIONS = [
    ("what_it_does", "What the controllers do, as found", "4-6 sentences: the identified control law per loop, "
     "the summer stop, how strongly each room responds, which structures the data could not separate."),
    ("evidence", "How sure we are", "3-5 sentences: held-out errors, the margin over no control, what the spot "
     "readings changed, what the operator beliefs and site context showed."),
    ("unknowns", "What the data cannot tell yet", "3-5 sentences: unobserved outdoor range, level vs slope, "
     "mechanisms that fit but are not supported, and why."),
    ("next", "Next observation", "2-3 sentences: state next_observation from the packet and what it would settle. Do not suggest changing the controller."),
    ("fi", "Yhteenveto huoltomiehelle (suomeksi)", "4-6 short sentences IN FINNISH for the technician on site: what "
     "the controller does, what is uncertain, what to read off the panel next. Plain spoken Finnish."),
]


GLOSSARY = {
    "delta_bic_curve_over_no_control": "model-comparison score: how much better the curve explains the room data than no control, after a complexity penalty. Over 10 is strong. NOT energy, NOT degrees.",
    "held_out_error_c": "prediction error of room temperature on weeks the fit never saw, degrees C",
    "heating_share_by_room": "each room's share of the loop's direct heating coupling, 0 to 1",
    "error_vs_other_panel_readings_c": "how far the fitted curve is from panel supply readings not used in the fit, degrees C",
    "controller_sensor_minus_fmi_c": "controller's own outdoor sensor minus the weather station, degrees C",
    "delta_bic_vs_blind_best": "positive = worse than the best program found without site context; over 2 is a real difference",
    "next_observation": "the cheapest next check, already chosen by the system - report it, do not invent another",
}


def grounded(ev) -> set[str]:
    """Numbers in the packet, plus their unsigned forms: prose writes 'slope of 0.69' for -0.69."""
    known = guardrails.known_numbers(ev)
    return known | {k.lstrip("-") for k in known}


def packet(real: dict, ctx: dict | None, syn: dict | None) -> dict:
    simple = {lid: {"name": s["name"], "rooms": s["rooms"],
                    "curve": {"supply_at_0c_outdoor_c": round(s["theta"]["level"], 1),
                              "slope_c_per_c": round(s["theta"]["slope"], 2),
                              "summer_stop_above_c": round(s["theta"]["cutoff"], 1)},
                    "held_out_error_c": s["held_rmse_rooms"],
                    "delta_bic_curve_over_no_control": round(s["vs_no_control"]["S0"]["bic"] - s["vs_no_control"]["S3"]["bic"], 1),
                    "windows": s["vs_no_control"]["windows"]}
              for lid, s in (real.get("simple") or {}).items()}
    loops = {lid: {"heating_share_by_room": L["heating_share"], "best_on_cold_weeks": L["ranked"][0]["id"] + " " + L["ranked"][0]["name"],
                   "runner_up_delta_bic": L["ranked"][1]["delta_bic"]}
             for lid, L in (real.get("loops") or {}).items() if L.get("ranked")}
    p = {
        "data": {"outdoor_station": real["data"]["outdoor"]["station"], "outdoor_min_c": real["data"]["outdoor"]["min_c"],
                 "outdoor_max_c": real["data"]["outdoor"]["max_c"],
                 "room_data_last_day": real["data"]["rooms"]["tv"]["last"][:10]},
        "loops_curve_fit_all_weeks": simple,
        "loops_cold_weeks": loops,
        "spot_readings": [{"readings_used": a["k"], "error_vs_other_panel_readings_c": a["rmse_vs_panel_l1_c"]}
                          for a in real["anchored_fireplace"]],
        "operator_beliefs": [{"belief": o.get("belief"), "verdict": o["verdict"]} for o in real["operator"]],
        "controller_sensor_minus_fmi_c": [c["offset_c"] for c in real["controller_vs_fmi"]],
        "site": real.get("site", {}).get("rooms", {}),
        "glossary": GLOSSARY,
    }
    ex = ART / "explain.json"
    if ex.is_file():
        nx = json.loads(ex.read_text(encoding="utf-8")).get("next_observation") or {}
        p["next_observation"] = nx.get("pick")
    if ctx:
        p["site_context_programs"] = [{"from": e["from_text"], "target": e["target"], "verdict": e["verdict"],
                                       "delta_bic_vs_blind_best": e.get("delta_bic_vs_blind_best")}
                                      for e in ctx["programs"]]
    if syn:
        p["synthetic_benchmark"] = {"cases": len(syn["cases"]),
                                    "right_mechanism_by_arm": {k: sum(1 for c in syn["cases"] if c["arms"][k].get("right_mechanism"))
                                                               for k in ("A", "B", "C")}}
    return p


def build() -> dict:
    cfg = client.config()
    real = json.loads((ART / "real.json").read_text(encoding="utf-8"))
    ctx = json.loads((ART / "context.json").read_text(encoding="utf-8")) if (ART / "context.json").is_file() else None
    syn = json.loads((ART / "synth.json").read_text(encoding="utf-8")) if (ART / "synth.json").is_file() else None
    ev = packet(real, ctx, syn)
    known = grounded(ev)
    out = {"llm": client.status(cfg), "model": cfg.get("model_text"), "sections": [], "dropped": [], "evidence": ev}
    if cfg["backend"] not in ("amd", "other", "archive"):
        out["status"] = "not written: no language model configured"
    else:
        for key, title, ask in SECTIONS:
            user = (f"Section: {title}\n{ask}\nReturn JSON {{\"lines\": [\"sentence\", ...]}}.\n\n"
                    f"Evidence:\n```json\n{json.dumps(ev, indent=1, ensure_ascii=False)}\n```")
            try:
                rep = client.chat(SYSTEM, user, purpose=f"writeup {key}", cfg=cfg, role="text")
            except client.LLMError as exc:
                out["sections"].append({"key": key, "title": title, "lines": [], "error": str(exc)[:200]})
                continue
            ans = client.extract_json(rep.text) or {}
            lines = [str(x) for x in (ans.get("lines", []) if isinstance(ans, dict) else ans if isinstance(ans, list) else [])]
            kept = []
            for line in lines:
                bad = guardrails.ungrounded_numbers(line, known)
                if bad:
                    out["dropped"].append({"section": key, "line": line, "ungrounded": bad})
                else:
                    kept.append(line)
            out["sections"].append({"key": key, "title": title, "lines": kept})
    (ART / "writeup.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote artifacts/writeup.json ({sum(len(s['lines']) for s in out['sections'])} lines kept, "
          f"{len(out['dropped'])} dropped by guardrails)")
    return out


if __name__ == "__main__":
    build()
