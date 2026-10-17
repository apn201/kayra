"""Arm B: non-LLM program search in the same structure language.

The baseline a sceptical judge will ask about. Best-first grammar expansion:
take the top programs so far, apply one or two random edits from a fixed
grammar, validate, fit, keep the best. Same budget of programs per round as the
language-model arm, same validator, same fitter. It uses the same operators the
model has, so it is not a straw man - what it lacks is a reason for each edit.
"""

from __future__ import annotations

import ast
import random

from . import dsl

EDITS = [
    "filter_outdoor", "cutoff", "cap", "room_p", "room_i", "thermostat", "outdoor_hysteresis",
    "night_setback", "weekday_gate",
]


def _fresh(params: dict, stem: str, typ: str) -> str:
    i = 1
    while f"{stem}{i}" in params:
        i += 1
    params[f"{stem}{i}"] = typ
    return f"{stem}{i}"


def mutate(spec: dict, rng: random.Random) -> dict:
    params = dict(spec["params"])
    e = spec["expr"]
    if e == "OFF":  # nothing to edit: start from a linear curve
        lv, sl = _fresh(params, "lv", "temp_c"), _fresh(params, "sl", "slope")
        e = f"{lv} + {sl} * T_out"
    edit = rng.choice(EDITS)
    if edit == "filter_outdoor" and "T_out" in e:
        t = _fresh(params, "tau", "hours")
        # replace the first bare T_out
        tree = ast.parse(e, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("ema", "lag", "hysteresis"):
                for a in node.args:
                    a._skip = True
        done = False
        class R(ast.NodeTransformer):
            def visit_Name(self, node):
                nonlocal done
                if node.id == "T_out" and not done and not getattr(node, "_skip", False):
                    done = True
                    return ast.parse(f"ema(T_out, {t})", mode="eval").body
                return node
        e = ast.unparse(R().visit(tree))
    elif edit == "cutoff":
        t, c = _fresh(params, "tau", "hours"), _fresh(params, "co", "temp_c")
        e = f"where(ema(T_out, {t}) < {c}, {e}, OFF)"
    elif edit == "cap":
        m = _fresh(params, "mx", "temp_c")
        e = f"min({e}, {m})"
    elif edit == "room_p":
        k, s = _fresh(params, "kp", "gain"), _fresh(params, "sp", "temp_c")
        e = f"{e} + {k} * ({s} - T_room)"
    elif edit == "room_i":
        s, ti = _fresh(params, "sp", "temp_c"), _fresh(params, "ti", "hours")
        e = f"{e} + integral({s} - T_room, {ti})"
    elif edit == "thermostat":
        lo, hi = _fresh(params, "lo", "temp_c"), _fresh(params, "hi", "temp_c")
        e = f"where(hysteresis(T_room, {lo}, {hi}), {e}, OFF)"
    elif edit == "outdoor_hysteresis":
        lo, hi = _fresh(params, "lo", "temp_c"), _fresh(params, "hi", "temp_c")
        e = f"where(hysteresis(T_out, {lo}, {hi}), {e}, OFF)"
    elif edit == "night_setback":
        on, off, dr = _fresh(params, "on", "clock_h"), _fresh(params, "off", "clock_h"), _fresh(params, "dr", "delta_c")
        e = f"where((hour_of_day() >= {on}) | (hour_of_day() < {off}), {e} - {dr}, {e})"
    elif edit == "weekday_gate":
        w, dr = _fresh(params, "wk", "clock_h"), _fresh(params, "dr", "delta_c")
        e = f"where(weekday() < {w}, {e}, {e} - {dr})"
    return {"params": params, "expr": e, "edit": edit}


def propose(ranked_specs: list[dict], n: int, rng: random.Random, seen: set[str]) -> list[dict]:
    """Up to n new valid programs, mutated from the top two so far."""
    out = []
    tries = 0
    while len(out) < n and tries < 200:
        tries += 1
        parent = ranked_specs[min(len(ranked_specs) - 1, rng.randrange(2))]
        child = mutate(parent, rng)
        if rng.random() < 0.3:
            child = mutate(child, rng) | {"edit": child["edit"] + "+"}
        try:
            prog = dsl.validate(child)
        except dsl.Rejected:
            continue
        if prog.expr in seen:
            continue
        seen.add(prog.expr)
        out.append({"id": f"B{len(seen)}", "name": f"grammar edit: {child['edit']} on {parent.get('id')}",
                    "params": child["params"], "expr": prog.expr, "source": "baseline-grammar",
                    "parent": parent.get("id")})
    return out
