"""Site-context arm: the model reads what a plant actually has lying around - operator notes and
controller menu labels - and turns each into a testable program for a named room or loop.

    python -m kayra.context        needs artifacts/real.json (the blind run) and a model

This is the job pattern matching cannot do: a fitter cannot read "outdoor temperature delay" on
a menu, or "the valve is almost closed" in a note, and turn it into a mechanism. The fitter still
decides: every program is fitted and scored exactly like the blind ones, on the same windows, and
compared with the blind best for its target.

Rules (BUILD.md, Site context): labels only, never values from the curve screen. The blind run
never gets this context; this is a separate arm, labelled everywhere.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import client, dsl, load, search
from .hypothesize import GRAMMAR

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts"
SITE = ROOT / "config" / "site.json"
LABELS = ROOT / "config" / "menu_labels.md"

TASK = """You also get site context: notes from the people who run this plant and the labels shown on the
controller's menus. Labels only - no values. Turn each piece of context that implies a control
mechanism into a program in the structure language, aimed at one target (a room, or a loop of rooms
that share one controller). If a piece of context cannot be written in the language, say so instead
of forcing it.

Return ONLY a JSON object:
{"programs": [{"target": "<room or loop id>", "from_text": "<the note or label it comes from, quoted>",
  "params": {...}, "expr": "...", "mechanism": "...", "refute": "what result would refute it"}],
 "not_expressible": [{"from_text": "...", "why": "..."}]}
Each program must be a COMPLETE control law for its target - what the whole controller asks for -
not a single term. A limit is a curve with that limit; a correction term is a curve plus that term;
a delay is a curve on the delayed outdoor. You may also write one program that combines every
mechanism the menu implies, if it fits the size limits.
At most 8 programs. No numbers anywhere.

"params" maps each parameter NAME to its TYPE, exactly like this example:
{"target": "L1", "from_text": "Max limit", "params": {"level": "temp_c", "slope": "slope", "mx": "temp_c"},
 "expr": "min(level + slope * T_out, mx)", "mechanism": "weather curve capped at a maximum supply",
 "refute": "the cap is fitted above every supply the curve reaches"}"""


def _targets(real: dict, site: dict) -> dict:
    t = {}
    for r, R in real["rooms"].items():
        t[r] = {"rooms": [r], "blind_best": R["ranked"][0]}
    for lid, L in (real.get("loops") or {}).items():
        if L.get("ranked"):
            t[lid] = {"rooms": L["rooms"], "blind_best": L["ranked"][0]}
        elif L.get("same_as_room") in t:  # a one-room loop is that room
            t[lid] = t[L["same_as_room"]]
    return t


def build(device: str | None = None, n: int = 2048, iters: int = 6) -> dict:
    device = device or search.device_auto()
    cfg = client.config()
    if cfg["backend"] not in ("amd", "other", "archive"):
        raise SystemExit("No language model configured - the context arm needs one.")
    real = json.loads((ART / "real.json").read_text(encoding="utf-8"))
    site = json.loads(SITE.read_text(encoding="utf-8"))
    labels = LABELS.read_text(encoding="utf-8")
    targets = _targets(real, site)
    notes = {lid: L.get("operator_notes", "") for lid, L in site["loops"].items()}
    notes |= {f"room {r}": v for r, v in site.get("rooms", {}).items()}
    packet = {"targets": {k: {"rooms": v["rooms"], "blind_best": {x: v["blind_best"][x] for x in ("id", "name", "rmse_held_c")}}
                          for k, v in targets.items()},
              "operator_notes": notes}
    user = f"Site context:\n\n{labels}\n\n```json\n{json.dumps(packet, indent=1)}\n```"
    rep = client.chat(GRAMMAR + "\n" + TASK, user, purpose="site context", cfg=cfg, role="code")
    ans = client.extract_json(rep.text) or {}
    if isinstance(ans, list):
        ans = {"programs": ans}
    props = [p for p in ans.get("programs", []) if isinstance(p, dict)][:8]

    # one repair turn for validator rejects, like the hypothesis loop
    rejects = []
    for i, p in enumerate(props):
        try:
            dsl.validate(p)
        except dsl.Rejected as exc:
            rejects.append({"index": i, "expr": p.get("expr"), "params": p.get("params"), "reason": str(exc)})
    repaired = 0
    if rejects:
        fix = "The validator rejected these. Return {\"programs\": [...]} with corrected versions, same targets:\n" + json.dumps(rejects, indent=1)
        try:
            rep2 = client.chat(GRAMMAR + "\n" + TASK, user + "\n\n" + fix, purpose="site context repair", cfg=cfg, role="code")
            ans2 = client.extract_json(rep2.text) or {}
            fixed = ans2.get("programs", []) if isinstance(ans2, dict) else ans2
            for rj, fx in zip(rejects, [x for x in fixed if isinstance(x, dict)]):
                fx["mechanism"] = (fx.get("mechanism") or "") + " (repaired after validator rejection)"
                fx.setdefault("target", props[rj["index"]].get("target"))
                fx.setdefault("from_text", props[rj["index"]].get("from_text"))
                props.append(fx)
                repaired += 1
        except client.LLMError:
            pass

    f = load.load()
    priors, problems = {}, {}
    entries = []
    for i, p in enumerate(props):
        tgt = p.get("target")
        e = {"id": f"C{i + 1}", "target": tgt, "from_text": p.get("from_text", ""), "expr": p.get("expr"),
             "params": p.get("params"), "mechanism": p.get("mechanism", ""), "refute": p.get("refute", ""),
             "source": f"site context ({client.status(cfg)})"}
        if tgt not in targets:
            e["verdict"] = f"unknown target {tgt!r}"
            entries.append(e)
            continue
        try:
            dsl.validate(dict(p, id=e["id"]))
        except dsl.Rejected as exc:
            e["verdict"] = f"rejected by validator: {exc}"
            entries.append(e)
            continue
        rooms = targets[tgt]["rooms"]
        for r in rooms:
            if r not in priors:
                priors[r] = search.summer_prior(f, r, device, n=n, iters=iters)
        key = tuple(rooms)
        if key not in problems:
            problems[key] = search.Problem(f, rooms if len(rooms) > 1 else rooms[0], device, season="cold",
                                           building=[priors[r]["bounds"] for r in rooms])
        prob = problems[key]
        res = search.search(prob, dict(p, id=e["id"]), n=n, iters=iters, seed=40 + i)
        row = search.rank([res], prob)[0]
        blind = targets[tgt]["blind_best"]
        d = row["bic"] - blind["bic"]
        e |= {"rmse_held_c": row["rmse_held_c"], "bic": row["bic"], "blind_best": blind["id"],
              "blind_best_rmse_c": blind["rmse_held_c"], "delta_bic_vs_blind_best": round(d, 2),
              "theta": res["best_theta"],
              "verdict": ("beats the blind best" if d < -2 else "ties the blind best" if d < 2
                          else "worse than the blind best")}
        entries.append(e)
        print(f"{e['id']} {tgt}: {e['verdict']} (dBIC {d:+.1f})  {p.get('expr')}")
    out = {"llm": client.status(cfg), "model": cfg.get("model_code"), "labels_file": "config/menu_labels.md",
           "programs": entries, "not_expressible": ans.get("not_expressible", []), "repaired": repaired,
           "note": "Separate arm. The blind run never sees site context. Labels only, no values."}
    (ART / "context.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote artifacts/context.json")
    return out


if __name__ == "__main__":
    build()
