"""The model's words: diagnosis per room, the next observation, alert explanations.

The rule: the model selects and explains, the deterministic layer computes. Each
request carries a JSON evidence packet; every line of the reply is checked with
guardrails.ungrounded_numbers against that packet, and a line carrying a number
the packet does not contain is dropped and logged. With no model online the
template text below ships instead, labelled TEMPLATE.

    python -m kayra.explain     reads artifacts/real.json, writes artifacts/explain.json
"""

from __future__ import annotations

import json
from pathlib import Path

from . import client, guardrails

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts"

SYSTEM = (
    "You are a controls engineer writing for the maintenance engineer who inherited an undocumented heating "
    "controller. You get a JSON evidence packet computed by a fitter. Write plain operator language, short "
    "sentences, no hype. Use only numbers that appear in the packet, copied exactly. Never estimate, convert or "
    "round a number into a new one. If the packet does not support a claim, do not make it. "
    "Every number you mention must be the value of a named field, and you must say what that field measures, "
    "using the glossary. A count is never a temperature. Do not mention numbers you do not need. "
    "Return ONLY JSON in the shape the user asks for."
)

GLOSSARY = {
    "rmse_held_c": "prediction error on held-out weeks, degrees C, lower is better",
    "delta_bic": "how much worse than the best program after a complexity penalty; under 2 is a tie",
    "prob": "share of belief among the programs tried, from the penalised scores",
    "time_constant_h": "how many hours the building takes to follow outdoor temperature",
    "cold_windows_count": "number of 72-hour stretches with mean outdoor under 12 C used for scoring (a count)",
    "mean_by_*": "mean of measured minus predicted room temperature, degrees C; negative = room colder than predicted",
    "heat_on_share_of_hours": "fraction of hours (0 to 1) the best program asks for heat",
    "corr_with_*": "correlation of the residual with that signal, -1 to 1",
}


def _check(lines: list[str], packet) -> tuple[list[str], list[dict]]:
    known = guardrails.known_numbers(packet)
    known |= {k.lstrip("-") for k in known}  # prose writes "slope of 0.69" for -0.69
    kept, dropped = [], []
    for line in lines:
        bad = guardrails.ungrounded_numbers(line, known)
        (dropped.append({"line": line, "ungrounded": bad}) if bad else kept.append(line))
    return kept, dropped


def _ask(task: str, packet: dict, shape: str, purpose: str, cfg) -> dict:
    user = f"{task}\n\nReturn JSON: {shape}\n\nEvidence:\n```json\n{json.dumps(packet, indent=1)}\n```"
    rep = client.chat(SYSTEM, user, purpose=purpose, cfg=cfg, role="text")
    out = client.extract_json(rep.text) or {}
    return out if isinstance(out, dict) else {}


def _room_packet(room: str, R: dict) -> dict:
    return {"room": room, "ranked": [{k: x[k] for k in ("id", "name", "source", "rmse_held_c", "delta_bic", "prob",
                                                        "tie_with_best")} for x in R["ranked"][:5]],
            "best_expr": R["best"]["expr"], "time_constant_h": R["best"]["time_constant_h"],
            "residual": R["residual"], "cold_windows_count": R["windows_cold"], "glossary": GLOSSARY}


def template_room(room: str, R: dict) -> list[str]:
    a, b = R["ranked"][0], R["ranked"][1]
    tie = b["delta_bic"] < 2
    lines = [f"Best explanation: {a['id']} {a['name']}, held-out error {a['rmse_held_c']} °C."]
    lines.append(f"Runner-up {b['id']} is within the noise (ΔBIC {b['delta_bic']}): the data do not separate them."
                 if tie else f"Runner-up {b['id']} trails by ΔBIC {b['delta_bic']}.")
    lines.append(f"Scored on {R['windows_cold']} cold windows; the building time constant is {R['best']['time_constant_h']} h.")
    return lines


def build() -> dict:
    real = json.loads((ART / "real.json").read_text(encoding="utf-8"))
    cfg = client.config()
    live = cfg["backend"] in ("amd", "other", "archive")
    out = {"llm": client.status(cfg), "rooms": {}, "next_observation": None, "alerts": [], "dropped": []}
    for room, R in real["rooms"].items():
        packet = _room_packet(room, R)
        template = template_room(room, R)
        lines, source = template, "TEMPLATE"
        if live:
            try:
                ans = _ask("Diagnose what controls this room, from the ranked programs and the residual. "
                           "Three to five sentences. Say plainly when the top programs tie.",
                           packet, '{"lines": ["sentence", ...]}', f"diagnosis {room}", cfg)
                kept, dropped = _check([str(x) for x in ans.get("lines", [])], packet)
                if kept:
                    lines, source = kept, client.status(cfg)
                out["dropped"] += [d | {"where": f"diagnosis {room}"} for d in dropped]
            except client.LLMError as exc:
                out["error"] = str(exc)
        # the template is the diagnosis; model wording is shown beside it, numbers checked, reasoning not
        out["rooms"][room] = {"template": template, "lines": lines, "source": source}

    # next observation: the cheapest check that would separate the survivors
    packet = {"rooms": {r: {"top_two": [x["id"] + " " + x["name"] for x in R["ranked"][:2]],
                            "runner_up_delta_bic": R["ranked"][1]["delta_bic"],
                            "residual_by_outdoor_band": R["residual"]["mean_by_outdoor_band"]}
                        for r, R in real["rooms"].items()},
              "observed_outdoor_c": [real["data"]["outdoor"]["min_c"], real["data"]["outdoor"]["max_c"]],
              "anchored": [{"k": a["k"], "rmse_vs_panel_l1_c": a["rmse_vs_panel_l1_c"]} for a in real["anchored_fireplace"]],
              "glossary": GLOSSARY,
              "options": ["one panel reading of both loops at the coldest outdoor of the coming week",
                          "a fresh Home Assistant pull covering the heating season since the last pull",
                          "the 5-minute data across the next fireplace evening",
                          "a night-time panel reading, to test for a night setback"]}
    nxt = {"pick": packet["options"][1], "why": "Room data stop before the heating season; every structure ties on what is there.",
           "source": "TEMPLATE"}
    if live:
        try:
            ans = _ask("Pick the single cheapest next observation from `options` that would best separate the "
                       "surviving hypotheses, and say why in at most two sentences.",
                       packet, '{"pick": "one of options, verbatim", "why": "..."}', "next observation", cfg)
            if ans.get("pick") in packet["options"]:
                kept, dropped = _check([str(ans.get("why", ""))], packet)
                nxt = {"pick": ans["pick"], "why": kept[0] if kept else "", "source": client.status(cfg)}
                out["dropped"] += [d | {"where": "next observation"} for d in dropped]
        except client.LLMError as exc:
            out["error"] = str(exc)
    out["next_observation"] = nxt

    for a in [x for x in real["alerts"]][:12]:
        text, source = f"{a['rule']} in {a['room']}: {a['kind']}.", "TEMPLATE"
        if live and a["kind"] == "ALERT":
            try:
                ans = _ask("Explain this alert to the operator in two sentences: what it means and what to check first.",
                           a, '{"text": "..."}', "alert", cfg)
                kept, dropped = _check([str(ans.get("text", ""))], a)
                if kept and kept[0]:
                    text, source = kept[0], client.status(cfg)
                out["dropped"] += [d | {"where": "alert"} for d in dropped]
            except client.LLMError:
                pass
        out["alerts"].append(a | {"text": text, "source": source})
    (ART / "explain.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote artifacts/explain.json ({len(out['dropped'])} lines dropped by guardrails)")
    return out


if __name__ == "__main__":
    build()
