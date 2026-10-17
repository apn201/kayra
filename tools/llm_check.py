#!/usr/bin/env python3
"""Check the language-model endpoint and score its models on Käyrä's own tasks.

    python tools/llm_check.py                    # every chat model the endpoint lists
    python tools/llm_check.py --models Qwen3.8-27B DeepSeek-V4.1-Flash

Uses KAYRA_LLM_BASE_URL / KAYRA_LLM_API_KEY from .env. If {base}/models is a 404 it
retries with /v1 appended and says so. Three tasks per model, all graded by code,
not by another model:

  programs   write hypothesis programs from a fixed evidence packet; graded by the
             structure-language validator (valid, distinct, no literals)
  operator   turn a plain-language operator note into a program; must use T_room
  prose      three sentences from a numbers packet; graded by guardrails (every
             number must be in the packet)

Writes artifacts/model_check.json and prints the recommended KAYRA_LLM_MODEL_CODE and
KAYRA_LLM_MODEL_TEXT. Every call is archived like any other.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kayra import client, dsl, guardrails  # noqa: E402
from kayra.hypothesize import PROMPT  # noqa: E402

SKIP = ("omnivoice", "mineru", "minicpm-v")  # speech, document parsing, small vision models

EVIDENCE = {
    "ranked_programs": [
        {"id": "S1", "expr": "level + slope * T_out", "params": {"level": "temp_c", "slope": "slope"}, "rmse_held_c": 0.36, "delta_bic": 0.0},
        {"id": "S0", "expr": "OFF", "params": {}, "rmse_held_c": 0.372, "delta_bic": 4.8},
        {"id": "S7", "expr": "where((hour_of_day() >= n_on) | (hour_of_day() < n_off), level - drop + slope * T_out, level + slope * T_out)",
         "params": {"level": "temp_c", "slope": "slope", "drop": "delta_c", "n_on": "clock_h", "n_off": "clock_h"}, "rmse_held_c": 0.374, "delta_bic": 17.7},
    ],
    "residual_report": {"mean_by_local_hour": {"2": -0.21, "4": -0.19, "8": 0.05, "14": 0.18, "20": 0.04},
                        "mean_by_outdoor_band": {"0-5": -0.12, "5-10": 0.02, "10-15": 0.09},
                        "weekend_minus_weekday": 0.08, "corr_with_outdoor": -0.23},
    "notebook": [],
}
OPERATOR_NOTE = ("The radiator in this room has an analog thermostatic valve, set almost closed. "
                 "Write ONE program for this room's heating that captures that.")
PROSE_PACKET = {"room": "fireplace", "best": "S1 weather curve", "rmse_held_c": 0.36, "runner_up": "S0 no control",
                "runner_up_delta_bic": 4.8, "cold_windows_count": 48,
                "glossary": {"rmse_held_c": "error on held-out weeks, degrees C",
                             "runner_up_delta_bic": "penalised score gap, under 2 is a tie",
                             "cold_windows_count": "number of 72-hour windows used (a count)"}}


def grade_programs(text: str) -> dict:
    props = client.extract_json(text) or []
    if isinstance(props, dict):
        props = props.get("programs") or [props]
    valid, reasons, exprs = 0, [], set()
    for p in props if isinstance(props, list) else []:
        try:
            prog = dsl.validate(p if isinstance(p, dict) else {})
            if prog.expr not in exprs:
                valid += 1
                exprs.add(prog.expr)
        except dsl.Rejected as exc:
            reasons.append(str(exc)[:80])
    return {"returned": len(props) if isinstance(props, list) else 0, "valid": valid, "rejects": reasons[:4]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*")
    a = ap.parse_args()
    cfg = client.config()
    if not cfg["base_url"] or not cfg["api_key"]:
        raise SystemExit("Set KAYRA_LLM_BASE_URL and KAYRA_LLM_API_KEY in .env first.")
    try:
        models = client.list_models(cfg)
    except client.LLMError as exc:
        if not cfg["base_url"].endswith("/v1"):
            cfg["base_url"] += "/v1"
            print(f"{exc}; retrying with {cfg['base_url']}")
            models = client.list_models(cfg)
            print(f"-> set KAYRA_LLM_BASE_URL={cfg['base_url']} in .env")
        else:
            raise
    print(f"endpoint {cfg['base_url']} lists {len(models)} models")
    todo = a.models or [m for m in models if not any(s in m.lower() for s in SKIP)]
    rows = []
    for m in todo:
        row = {"model": m}
        for task, (system, user, role) in {
            "programs": (PROMPT, "Round 1.\n\n```json\n" + json.dumps(EVIDENCE, indent=1) + "\n```", "code"),
            "operator": (PROMPT, OPERATOR_NOTE + "\n\nReturn a JSON array with one program.", "code"),
            "prose": ("Write for a maintenance engineer. Use only numbers from the packet, copied exactly. "
                      "Return JSON {\"lines\": [three sentences]}.", json.dumps(PROSE_PACKET), "text"),
        }.items():
            t0 = time.time()
            try:
                rep = client.chat(system, user, purpose=f"model check {task}", cfg=cfg, role=role, model=m)
                dt = round(time.time() - t0, 1)
                if task == "programs":
                    row[task] = grade_programs(rep.text) | {"s": dt}
                elif task == "operator":
                    g = grade_programs(rep.text)
                    props = client.extract_json(rep.text) or []
                    exprs = [p.get("expr", "") for p in (props if isinstance(props, list) else [props]) if isinstance(p, dict)]
                    row[task] = {"valid": g["valid"], "uses_room": any("T_room" in e for e in exprs), "s": dt}
                else:
                    lines = (client.extract_json(rep.text) or {}).get("lines", []) if isinstance(client.extract_json(rep.text), dict) else []
                    known = guardrails.known_numbers(PROSE_PACKET)
                    bad = [l for l in lines if guardrails.ungrounded_numbers(str(l), known)]
                    row[task] = {"lines": len(lines), "grounded": len(lines) - len(bad), "s": dt}
            except client.LLMError as exc:
                row[task] = {"error": str(exc)[:120]}
        p, o, q = row.get("programs", {}), row.get("operator", {}), row.get("prose", {})
        row["score_code"] = p.get("valid", 0) + 2 * int(o.get("valid", 0) > 0 and o.get("uses_room", False))
        row["score_text"] = q.get("grounded", 0) - (q.get("lines", 0) - q.get("grounded", 0)) * 2
        rows.append(row)
        print(json.dumps(row))
    ok = [r for r in rows if "error" not in r.get("programs", {})]
    if not ok:
        raise SystemExit("no model answered")
    speed = lambda r: sum(r.get(t, {}).get("s", 99) for t in ("programs", "operator", "prose"))
    code = max(ok, key=lambda r: (r["score_code"], -speed(r)))
    text = max(ok, key=lambda r: (r["score_text"], -speed(r)))
    out = {"base_url": cfg["base_url"], "listed": models, "rows": rows,
           "recommend": {"KAYRA_LLM_MODEL_CODE": code["model"], "KAYRA_LLM_MODEL_TEXT": text["model"]}}
    (ROOT / "artifacts").mkdir(exist_ok=True)
    (ROOT / "artifacts" / "model_check.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("\nrecommended:")
    for k, v in out["recommend"].items():
        print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
